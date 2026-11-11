"""Storage: the three tables of reference/schema.sql, and scoped loading.

The store holds exactly Items, Connections and Assertions (I-1). Triple uniqueness and one
Connection per ordered pair are enforced by primary keys (2.2.1, 2.3.2, I-2, I-4).

Reads load only the records relevant to their scope (9.10.1): the scope's forward closure,
the Assertions about its members, the acts that reference those records, and the context and
source Items involved, followed transitively. ``load_all`` exists for reads that name no
scope, which the conformance contract allows only in fixtures (README §5).

Finding records by the references in their JSON (2.4.5) does not require reading the whole
store. Exact-read dependents and removal use the expression indexes over
``identifier_entries(...)`` in reference/schema.sql. An entry is a string held at
any depth by an identifier member, filed as ``item:`` (members ``id``, ``item``, ``from``,
``to``), ``context:`` or ``source:``, for example ``item:door-101``. Given some entries, the
index yields the records that hold one of them, and the exact test is then applied to those
candidates only. Loading uses the narrower ``discovery_entries(...)``, which holds only the
strings at the discovery positions (``_DISCOVERY_PATHS``): a record that names an Item as its
``@party`` or in its ``@frame`` is not fetched when that Item's records are loaded, because
no rule follows those members. Each step of the closure issues two queries, one for Items
and one for Assertions, whatever the number of ids in the step.

Every query given a set of ids or entries joins the set, passed as an array, to the indexed
lookup of each element (``unnest`` and a ``LATERAL`` subquery with ``OFFSET 0``). Each
element is then one index search, and no plan evaluates an expression index's function on
every row of a table, whatever the size of the set.

Normalizations (7.3.8) are found from the Connections into a subject and its ancestors,
which decide the scopes it belongs to at each instant: those already loaded (a scope's reach),
and those entering them from elsewhere (``incoming_from_outside``, ``ancestor_connections``);
and then the normalizations whose scope Item is one of those Items, or whose corrected content
names one (``normalization_rows_for_scopes``, one scan of a partial index keyed by the scope
Item). Normalizations of scopes that cannot reach the subjects are not read, so their number in
unrelated scopes does not change what a read or a write loads (9.10.1). A partial index that
holds only the normalizations (``has_normalizations``) lets a store without one answer the
lookup without reading any other record.

The record-perspective listing reads load the records of the units of work in scope instead
of the scope's whole closure (``load_listing``, spec 7.6.14, 9.10.1): the stories about the
scope's members, the expectations about them, the extension records that name them and the
lifecycle acts of the scope's Connections, and then, step by step, the acts that target what
is loaded (``target_entries(...)``), the contexts and the publications of the milestones
involved.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

from .model import DECLARED_REFERENCE_EXTENSION, Item, Triple, act_targets, ref_list
from .values import from_json_text, iter_refs, ref_item_ids, to_json_text

# Reserved members whose references create dependencies that reads must follow (2.4.5).
_LIST_REF_KEYS = ("@targets", "@basis", "@establishes", "@reaffirms")
_SINGLE_REF_KEYS = ("@after", "@relates_to", "@successor", "@representative", "@issuance")
_FOLLOW_KEYS = set(_LIST_REF_KEYS) | set(_SINGLE_REF_KEYS) | {"@corrected", "@story", "@transitions"}


@dataclass
class RawAssertion:
    triple: Triple
    values: dict
    recorded_at: object = None
    recorded_by: str | None = None


@dataclass
class RecordSet:
    """Records loaded from the store, as recorded (no correction applied)."""

    items: dict[str, Item] = field(default_factory=dict)
    assertions: dict[Triple, RawAssertion] = field(default_factory=dict)
    connections: dict[tuple[str, str], dict] = field(default_factory=dict)
    complete: bool = False
    # The Items whose outgoing, and whose incoming, Connections are all in ``connections``
    # (loading bookkeeping, so that the normalization lookup does not fetch them again)
    out_complete: set = field(default_factory=set)
    in_complete: set = field(default_factory=set)
    # The Items for which a normalization lookup found that no normalization applies (7.3.8), so
    # that an evaluation of some of them on another record set needs no lookup of its own
    no_normalization: set = field(default_factory=set)

    def copy(self) -> "RecordSet":
        return RecordSet(dict(self.items), dict(self.assertions), dict(self.connections), self.complete,
                         set(self.out_complete), set(self.in_complete), set(self.no_normalization))

    def without(self, triple: Triple | None = None, item_id: str | None = None) -> "RecordSet":
        rs = self.copy()
        if triple is not None:
            rs.assertions.pop(triple, None)
        if item_id is not None:
            rs.items.pop(item_id, None)
        return rs

    def size(self) -> int:
        return len(self.items) + len(self.assertions) + len(self.connections)


def _discovery_paths() -> tuple[tuple[str, ...], ...]:
    """The positions in an Assertion's values through which an act references a record about
    an Item (the Item itself, an Assertion with it as a coordinate, or a Connection touching
    it) via a reserved member. Each is a path of member names, where ``[]`` steps into every
    element of a list; the last name is the identifier member that holds the Item id."""
    paths: list[tuple[str, ...]] = []
    for key in _LIST_REF_KEYS:
        paths += [(key, "[]", "item"), (key, "[]", "id"), (key, "[]", "from"), (key, "[]", "to"),
                  ("@corrected", key, "[]", "item")]
    paths.append(("@targets", "[]", "support", "item"))
    for key in _SINGLE_REF_KEYS:
        paths += [(key, "item"), (key, "id"), ("@corrected", key, "item")]
    paths += [("@corrected", "item"), ("@story", "subject", "id"),
              ("@transitions", "[]", "prior", "item"), ("@transitions", "[]", "new", "item")]
    return tuple(paths)


_DISCOVERY_PATHS = _discovery_paths()
# identifier_entries (reference/schema.sql) files the string held by an id, item, from or to
# member under "item:", and the string held by a context or source member under its name.
_ITEM_MEMBERS = frozenset({"id", "item", "from", "to"})
assert {path[-1] for path in _DISCOVERY_PATHS} <= _ITEM_MEMBERS
# discovery_entries (reference/schema.sql) files the strings at the @issuance positions with
# the prefix U+001E, so that a load can leave them out (Store.load_closure, issuance=False).
_ISSUANCE_MARK = "\x1e"
_ISSUANCE_PATHS = tuple(p for p in _DISCOVERY_PATHS if "@issuance" in p)
_NON_ISSUANCE_PATHS = tuple(p for p in _DISCOVERY_PATHS if "@issuance" not in p)

# Members that name an Item to identify a participant, the frame an act was recorded in, the
# communication that carries it, or attribution and distribution lists (2.4.4, 3.1.2, 3.2.1,
# 4.4.2). They give a write no dependency on the records of the Items they name: no rule of
# validation (10.2) or maintenance (7.2.8, 7.6.9) reads those records because of them.
IDENTIFYING_MEMBERS = frozenset({"@party", "@frame", "@issuance", "@producer", "@agent", "@distribution"})


def dependency_refs(value) -> list[dict]:
    """The references in a value, at any depth, except those inside the identifying members
    (``IDENTIFYING_MEMBERS``)."""
    out: list[dict] = []
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            if "@ref" in v:
                out.append(v)
            stack.extend(x for k, x in v.items() if k not in IDENTIFYING_MEMBERS)
        elif isinstance(v, list):
            stack.extend(v)
    return out


def discovered_item_ids(values: dict, issuance: bool = True) -> set[str]:
    """Item ids whose records an Assertion references through a reserved member, at the
    positions of ``_DISCOVERY_PATHS`` (without the ``@issuance`` positions when ``issuance`` is
    false): the acts that loading a record set adds for those Items (2.4.5). Each path ends at
    an ``item``, ``id``, ``from`` or ``to`` member, and ``discovery_entries("values")`` holds
    every id returned, so the discovery index finds every Assertion this function would
    select."""
    out: set[str] = set()
    for path in (_DISCOVERY_PATHS if issuance else _NON_ISSUANCE_PATHS):
        nodes = [values]
        for step in path[:-1]:
            if step == "[]":
                nodes = [e for n in nodes if isinstance(n, list) for e in n]
            else:
                nodes = [n[step] for n in nodes if isinstance(n, dict) and step in n]
        leaf = path[-1]
        out |= {n[leaf] for n in nodes if isinstance(n, dict) and isinstance(n.get(leaf), str)}
    return out


# target_entries (reference/schema.sql): one entry per reference that targets, supports,
# follows, corrects or relocates to a record. The parts are separated by U+001F.
_SEP = "\x1f"


def assertion_entry(triple: Triple) -> str:
    return "a" + _SEP.join(triple)


def item_entry(item_id: str) -> str:
    return "i" + item_id


def connection_entry(pair: tuple[str, str]) -> str:
    return "c" + pair[0] + _SEP + pair[1]


def _ref_entry(ref: dict) -> str | None:
    kind = ref.get("@ref")
    if kind == "assertion" and all(isinstance(ref.get(k), str) for k in ("item", "context", "source")):
        return assertion_entry((ref["item"], ref["context"], ref["source"]))
    if kind == "item" and isinstance(ref.get("id"), str):
        return item_entry(ref["id"])
    if kind == "connection" and isinstance(ref.get("from"), str) and isinstance(ref.get("to"), str):
        return connection_entry((ref["from"], ref["to"]))
    return None


def target_entry_keys(values: dict) -> set[str]:
    """The entries ``target_entries(values)`` holds at least: the references in ``@targets``
    and their support selectors, in ``@establishes``, ``@reaffirms`` and ``@after``, and every
    reference at any depth of ``@corrected``."""
    refs: list[dict] = []
    for key in ("@targets", "@establishes", "@reaffirms"):
        v = values.get(key)
        if isinstance(v, list):
            refs += [r for r in v if isinstance(r, dict)]
    refs += [r["support"] for r in (values.get("@targets") if isinstance(values.get("@targets"), list) else [])
             if isinstance(r, dict) and isinstance(r.get("support"), dict)]
    if isinstance(values.get("@after"), dict):
        refs.append(values["@after"])
    refs += list(iter_refs(values.get("@corrected")))
    return {e for e in (_ref_entry(r) for r in refs) if e is not None}


def followed_item_ids(values: dict, issuance: bool = True) -> set[str]:
    """Item ids that loading follows from an Assertion: the references in reserved members
    that carry dependencies. Participant lists, frames and domain property values are not
    followed; they identify, they do not depend. Without ``issuance``, ``@issuance`` is not
    followed either (``Store.load_closure``)."""
    out: set[str] = set()
    for key, v in values.items():
        if key in _FOLLOW_KEYS and (issuance or key != "@issuance"):
            for r in iter_refs(v):
                out |= ref_item_ids(r)
    return out


def _text_array(xs: list):
    """A list of strings as the text of a PostgreSQL array (every element quoted, with ``\\``
    and ``"`` escaped), which the server parses where the query casts it to ``text[]`` or
    compares it with ``= ANY``. Passing the text instead of the list spares the driver
    inspecting and dumping each element of a large list; the server receives the same array.
    Any other list is passed as it is."""
    if not all(type(x) is str for x in xs):
        return xs
    return "{" + ",".join('"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"' for x in xs) + "}"


class _Parsed:
    """The parse of stored JSON texts, once per distinct text within one fetch. Many Items
    share a definition (the event contexts of the acts maintenance records at one instant)
    and many Connections share their properties; the library never changes a loaded
    definition or Connection's properties in place, so one parsed object can serve them all."""

    def __init__(self) -> None:
        self.seen: dict[str, object] = {}

    def __call__(self, text: str):
        v = self.seen.get(text)
        if v is None:
            v = self.seen[text] = from_json_text(text)
        return v


def definition_item_ids(definition: dict) -> set[str]:
    out: set[str] = set()
    ctx = definition.get("@context")
    if isinstance(ctx, dict):
        for r in iter_refs(ctx):
            out |= ref_item_ids(r)
    return out


class Store:
    """SQL access to one Attedra store on a psycopg connection."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self.loaded_rows = 0  # rows read since construction (locality measurement)

    # -- row access ---------------------------------------------------------------------

    def _q(self, sql: str, params=()):
        if params:
            params = tuple(_text_array(p) if isinstance(p, list) else p for p in params)
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
        self.loaded_rows += len(rows)
        return rows

    def no_jit(self) -> None:
        """Turn off JIT compilation for the current transaction (``SET LOCAL``). The joined
        lookups of this module are many short index searches whose row estimates the planner
        cannot know in advance (each element of an array is a parameter), so their estimated
        cost often exceeds the JIT threshold although they run in milliseconds; compiling them
        would cost more than running them. Plans and results are unchanged."""
        with self.conn.cursor() as cur:
            cur.execute("SET LOCAL jit = off")

    def _exec(self, sql: str, params=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    @staticmethod
    def _item(row) -> Item:
        return Item(row[0], row[1], row[2], from_json_text(row[3]))

    @staticmethod
    def _assertion(row) -> RawAssertion:
        return RawAssertion((row[0], row[1], row[2]), from_json_text(row[3]), row[4], row[5])

    _A_COLS = 'item_id, context_id, source_id, "values"::text, recorded_at, recorded_by'

    def get_item(self, item_id: str) -> Item | None:
        rows = self._q("SELECT id, kind, label, definition::text FROM items WHERE id = %s", (item_id,))
        return self._item(rows[0]) if rows else None

    # Joined lookups (module docstring): each element of the array is one index search.
    _A_COLS_A = 'a.item_id, a.context_id, a.source_id, a."values"::text, a.recorded_at, a.recorded_by'
    _BY_ITEM = (f"SELECT {_A_COLS_A} FROM unnest(%s::text[]) AS k(id) CROSS JOIN LATERAL "
                "(SELECT * FROM assertions WHERE item_id = k.id OFFSET 0) AS a")
    _BY_TRIPLE = (f"SELECT {_A_COLS_A} FROM unnest(%s::text[], %s::text[], %s::text[]) AS k(i, c, s) "
                  "CROSS JOIN LATERAL (SELECT * FROM assertions WHERE item_id = k.i AND context_id = k.c "
                  "AND source_id = k.s OFFSET 0) AS a")
    _BY_SELF_CONTEXT = (f"SELECT {_A_COLS_A} FROM unnest(%s::text[]) AS k(id) CROSS JOIN LATERAL "
                        "(SELECT * FROM assertions WHERE item_id = k.id AND context_id = k.id OFFSET 0) AS a")
    _BY_SUBJECT_SOURCE = (f"SELECT {_A_COLS_A} FROM unnest(%s::text[], %s::text[]) AS k(i, s) CROSS JOIN LATERAL "
                          "(SELECT * FROM assertions WHERE item_id = k.i AND source_id = k.s OFFSET 0) AS a")
    _TARGETING = (f"SELECT {_A_COLS_A} FROM unnest(%s::text[]) AS k(e) CROSS JOIN LATERAL "
                  '(SELECT * FROM assertions WHERE target_entries("values") @> ARRAY[k.e] OFFSET 0) AS a')

    def items(self, ids: Iterable[str]) -> list[Item]:
        ids = sorted(set(ids))
        if not ids:
            return []
        rows = self._q("SELECT i.id, i.kind, i.label, i.definition::text FROM unnest(%s::text[]) AS k(id) "
                       "CROSS JOIN LATERAL (SELECT * FROM items WHERE id = k.id OFFSET 0) AS i", (ids,))
        parsed = _Parsed()
        return [Item(r[0], r[1], r[2], parsed(r[3])) for r in rows]

    def item_exists(self, item_id: str) -> bool:
        return bool(self._q("SELECT 1 FROM items WHERE id = %s", (item_id,)))

    def get_assertion(self, triple: Triple) -> RawAssertion | None:
        rows = self._q(f"SELECT {self._A_COLS} FROM assertions WHERE item_id = %s AND context_id = %s AND source_id = %s",
                       triple)
        return self._assertion(rows[0]) if rows else None

    def assertion_exists(self, triple: Triple) -> bool:
        return bool(self._q("SELECT 1 FROM assertions WHERE item_id = %s AND context_id = %s AND source_id = %s", triple))

    def get_connection(self, a: str, b: str) -> dict | None:
        rows = self._q("SELECT properties::text FROM connections WHERE from_id = %s AND to_id = %s", (a, b))
        return from_json_text(rows[0][0]) if rows else None

    def assertions_about_or_referencing(self, ids: Iterable[str], issuance: bool = True) -> list[RawAssertion]:
        """The Assertions about these Items, then the acts that reference records about them
        through a reserved member (2.4.5), in one query whatever the number of ids. For each
        id, the primary key serves the first part and the discovery index the second;
        each id is one search of each index, so a large set of ids is never answered by
        evaluating ``discovery_entries`` on every row. Of the index's candidates, only the
        acts that reference an id at a discovery position (``discovered_item_ids``) are
        kept; a record found for several ids is kept once. Without ``issuance``, the acts that
        name an id only as the communication carrying them (``@issuance``) are not searched."""
        ids = sorted(set(ids))
        if not ids:
            return []
        wanted = set(ids)
        about: list[RawAssertion] = []
        referencing: list[RawAssertion] = []
        seen: set[Triple] = set()
        cond = ('discovery_entries("values") && ARRAY[k.id, %s || k.id]' if issuance
                else 'discovery_entries("values") @> ARRAY[k.id]')
        params = (ids, _ISSUANCE_MARK) if issuance else (ids,)
        sql = (f"SELECT {self._A_COLS_A} FROM unnest(%s::text[]) AS k(id) CROSS JOIN LATERAL "
               "(SELECT * FROM assertions WHERE item_id = k.id UNION ALL "
               f"SELECT * FROM assertions WHERE {cond} AND item_id <> k.id OFFSET 0) AS a")
        for r in self._q(sql, params):
            t = (r[0], r[1], r[2])
            if t in seen:
                continue
            seen.add(t)
            a = self._assertion(r)
            if a.triple[0] in wanted:
                about.append(a)
            elif discovered_item_ids(a.values, issuance) & wanted:
                referencing.append(a)
        return about + referencing

    def assertions_by_source(self, source: str) -> list[RawAssertion]:
        return [self._assertion(r) for r in self._q(
            f"SELECT {self._A_COLS} FROM assertions WHERE source_id = %s", (source,))]

    def assertions_at_context(self, context: str) -> list[RawAssertion]:
        return [self._assertion(r) for r in self._q(
            f"SELECT {self._A_COLS} FROM assertions WHERE context_id = %s", (context,))]

    def assertions_containing(self, pattern: dict) -> list[RawAssertion]:
        return [self._assertion(r) for r in self._q(
            f'SELECT {self._A_COLS} FROM assertions WHERE "values" @> %s::jsonb', (json.dumps(pattern),))]

    def connections_touching(self, ids: Iterable[str]) -> dict[tuple[str, str], dict]:
        ids = sorted(set(ids))
        if not ids:
            return {}
        rows = self._q("SELECT c.from_id, c.to_id, c.properties::text FROM unnest(%s::text[]) AS k(id) "
                       "CROSS JOIN LATERAL (SELECT * FROM connections WHERE from_id = k.id UNION ALL "
                       "SELECT * FROM connections WHERE to_id = k.id AND from_id <> k.id OFFSET 0) AS c", (ids,))
        parsed = _Parsed()
        return {(r[0], r[1]): parsed(r[2]) for r in rows}

    def reach(self, scope_id: str) -> set[str]:
        """Every Item reachable forward from a scope Item over Connections in any state
        (2.1.5). Active state at a cutoff is derived afterwards from the lifecycle acts.

        Each step looks up the outgoing Connections of each Item reached so far through the
        primary key. The step is a LATERAL subquery with OFFSET 0, which keeps
        PostgreSQL from turning it into a join that hashes the whole connections table at
        every step."""
        rows = self._q(
            """WITH RECURSIVE reach(id) AS (
                   SELECT to_id FROM connections WHERE from_id = %s
                   UNION
                   SELECT c.to_id FROM reach r
                   CROSS JOIN LATERAL (SELECT to_id FROM connections WHERE from_id = r.id OFFSET 0) AS c)
               SELECT id FROM reach""", (scope_id,))
        return {r[0] for r in rows}

    # -- exact references (exact-read dependents and removal, 2.4.5, 8.5.2) ----------------
    #
    # Each query is complete without reading the whole store. An exact reference to a record
    # is an object whose identifier members hold that record's ids as strings, so every
    # match holds the corresponding entries and is among the rows the identifier index
    # returns for them; the jsonpath condition then selects the matches exactly. The
    # conditions use strict mode, so an identifier member matches only when it holds a
    # string, the only shape validation admits (10.2.4); a lax condition would also match
    # array-valued members, which the index does not hold. On validated records the two
    # modes select the same rows.

    _REFS_ASSERTION = ('strict $.** ? (@."@ref" == "assertion" && @.item == $i && @.context == $c '
                       '&& @.source == $s)')
    _REFS_ITEM = ('strict $.** ? ((@."@ref" == "item" && @.id == $x) || '
                  '(@."@ref" == "assertion" && (@.item == $x || @.context == $x || @.source == $x)) || '
                  '(@."@ref" == "connection" && (@.from == $x || @.to == $x)))')

    def referencing_assertion(self, triple: Triple) -> list[RawAssertion]:
        """Every Assertion whose values reference this Assertion exactly, at any depth (2.4.5)."""
        vars_ = json.dumps({"i": triple[0], "c": triple[1], "s": triple[2]})
        return [self._assertion(r) for r in self._q(
            f'SELECT {self._A_COLS} FROM assertions WHERE identifier_entries("values") @> %s::text[] '
            'AND jsonb_path_exists("values", %s::jsonpath, %s::jsonb)',
            ([f"item:{triple[0]}", f"context:{triple[1]}", f"source:{triple[2]}"], self._REFS_ASSERTION, vars_))]

    def referencing_item(self, item_id: str) -> tuple[list[RawAssertion], list[Item]]:
        """Every Assertion and Item definition that references the Item in any form (2.4.5)."""
        vars_ = json.dumps({"x": item_id})
        entries = [f"item:{item_id}", f"context:{item_id}", f"source:{item_id}"]
        a = [self._assertion(r) for r in self._q(
            f'SELECT {self._A_COLS} FROM assertions WHERE identifier_entries("values") && %s::text[] '
            'AND jsonb_path_exists("values", %s::jsonpath, %s::jsonb)',
            (entries, self._REFS_ITEM, vars_))]
        i = [self._item(r) for r in self._q(
            "SELECT id, kind, label, definition::text FROM items WHERE identifier_entries(definition) && %s::text[] "
            "AND jsonb_path_exists(definition, %s::jsonpath, %s::jsonb)",
            (entries, self._REFS_ITEM, vars_))]
        return a, i

    def assertions_using_item(self, item_id: str) -> list[RawAssertion]:
        return [self._assertion(r) for r in self._q(
            f"SELECT {self._A_COLS} FROM assertions WHERE item_id = %s OR context_id = %s OR source_id = %s",
            (item_id, item_id, item_id))]

    # 10.4.4: the condition that a document carries the declared non-standard-reference
    # extension member in an object at any depth (``model.carries_member``). The member is a
    # constant of the library, so the condition is part of the SQL text. It is the predicate
    # of the two partial indexes in reference/schema.sql, which hold only the records that
    # carry the member, so the check below reads none of the others.
    _CARRIES_DECLARED_EXTENSION = f"""'$.** ? (exists (@."{DECLARED_REFERENCE_EXTENSION}"))'"""

    def declared_extension_in_store(self) -> bool:
        """Whether any Assertion's values or Item's definition in the store carries the
        declared extension (10.4.4, 10.3)."""
        cond = self._CARRIES_DECLARED_EXTENSION
        rows = self._q(f'SELECT EXISTS (SELECT 1 FROM assertions WHERE "values" @? {cond}) '
                       f'OR EXISTS (SELECT 1 FROM items WHERE definition @? {cond})')
        return bool(rows[0][0])

    # -- writes -------------------------------------------------------------------------

    def insert_item(self, item: Item) -> None:
        self._exec("INSERT INTO items (id, kind, label, definition) VALUES (%s, %s, %s, %s::jsonb)",
                   (item.id, item.kind, item.label, to_json_text(item.definition)))

    def insert_assertion(self, triple: Triple, values: dict, recorded_at=None, recorded_by=None) -> None:
        self._exec('INSERT INTO assertions (item_id, context_id, source_id, "values", recorded_at, recorded_by) '
                   "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                   (*triple, to_json_text(values), recorded_at, recorded_by))

    def insert_many(self, items: list[Item], assertions: list[tuple[Triple, dict]]) -> None:
        """Insert several Items, then several Assertions, each set in one pipelined batch."""
        with self.conn.cursor() as cur:
            if items:
                cur.executemany("INSERT INTO items (id, kind, label, definition) VALUES (%s, %s, %s, %s::jsonb)",
                                [(it.id, it.kind, it.label, to_json_text(it.definition)) for it in items])
            if assertions:
                cur.executemany('INSERT INTO assertions (item_id, context_id, source_id, "values", recorded_at, '
                                "recorded_by) VALUES (%s, %s, %s, %s::jsonb, NULL, NULL)",
                                [(*t, to_json_text(v)) for t, v in assertions])

    def insert_connection(self, a: str, b: str, properties: dict) -> None:
        self._exec("INSERT INTO connections (from_id, to_id, properties) VALUES (%s, %s, %s::jsonb)",
                   (a, b, to_json_text(properties)))

    def update_connection(self, a: str, b: str, properties: dict) -> None:
        self._exec("UPDATE connections SET properties = %s::jsonb WHERE from_id = %s AND to_id = %s",
                   (to_json_text(properties), a, b))

    def delete_assertion(self, triple: Triple) -> int:
        return self._exec("DELETE FROM assertions WHERE item_id = %s AND context_id = %s AND source_id = %s", triple)

    def delete_item(self, item_id: str) -> int:
        return self._exec("DELETE FROM items WHERE id = %s", (item_id,))

    # -- loading ------------------------------------------------------------------------

    def load_all(self) -> RecordSet:
        rs = RecordSet(complete=True)
        for r in self._q("SELECT id, kind, label, definition::text FROM items"):
            it = self._item(r)
            rs.items[it.id] = it
        for r in self._q(f"SELECT {self._A_COLS} FROM assertions"):
            a = self._assertion(r)
            rs.assertions[a.triple] = a
        for r in self._q("SELECT from_id, to_id, properties::text FROM connections"):
            rs.connections[(r[0], r[1])] = from_json_text(r[2])
        return rs

    def load_closure(self, seeds: Iterable[str], rs: RecordSet | None = None,
                     with_connections: Iterable[str] = (), issuance: bool = True) -> RecordSet:
        """Load the records relevant to ``seeds``: the Assertions about them, the
        acts that reference those records, and, transitively, the Items those records name
        in their coordinates and dependency-carrying references. Without ``issuance`` (the
        write path), the communication an act names in ``@issuance`` is neither followed nor
        searched: it matters only to a participant perspective (4.4.2, 4.6.1), which neither
        validation nor maintenance evaluates."""
        rs = rs or RecordSet()
        if rs.complete:
            return rs
        pending = set(seeds)
        seen: set[str] = set()
        while pending:
            batch = sorted(pending - seen)
            pending = set()
            if not batch:
                break
            seen |= set(batch)
            new_ids: set[str] = set()
            for it in self.items(batch):
                rs.items[it.id] = it
                new_ids |= definition_item_ids(it.definition)
            for a in self.assertions_about_or_referencing(batch, issuance):
                if a.triple in rs.assertions:
                    continue
                rs.assertions[a.triple] = a
                new_ids |= set(a.triple)
                new_ids |= followed_item_ids(a.values, issuance)
            pending = new_ids - seen
        conn_ids = set(with_connections)
        if conn_ids:
            rs.connections.update(self.connections_touching(conn_ids))
            rs.out_complete |= conn_ids
            rs.in_complete |= conn_ids
        return rs

    def load_scope(self, scope_id: str, rs: RecordSet | None = None) -> tuple[RecordSet, set[str]]:
        """Load a scope Item's forward closure (2.1.5) and everything relevant to it.
        Returns the record set and the candidate members (reachable in any state); the
        members active at a cutoff are derived from the lifecycle acts."""
        candidates = self.reach(scope_id)
        rs = self.load_closure(candidates | {scope_id}, rs, with_connections=candidates | {scope_id})
        return rs, candidates

    # -- loading the units of work in scope (7.6.14, 9.10.1) ------------------------------

    def reach_connections(self, scope_id: str) -> dict[tuple[str, str], dict]:
        """The Connections leaving the scope Item and every Item reachable forward from it,
        in any state (2.1.5), in one recursive query: the Connections scope membership at a
        cutoff is derived from (view.scope_members)."""
        rows = self._q(
            """WITH RECURSIVE reach(id) AS (
                   SELECT %s::text
                   UNION
                   SELECT c.to_id FROM reach r
                   CROSS JOIN LATERAL (SELECT to_id FROM connections WHERE from_id = r.id OFFSET 0) AS c)
               SELECT c.from_id, c.to_id, c.properties::text FROM reach r
               CROSS JOIN LATERAL (SELECT * FROM connections WHERE from_id = r.id OFFSET 0) AS c""", (scope_id,))
        parsed = _Parsed()
        return {(r[0], r[1]): parsed(r[2]) for r in rows}

    def load_listing(self, scope_id: str | None, subjects: set[str] | None, items: set[str] = frozenset()
                     ) -> tuple[RecordSet, set[str] | None]:
        """The records a record-perspective listing read evaluates (7.6.14, 9.10.1), without
        the scope's whole closure. Given a scope Item, the Connections reached from it, and
        the candidate members (any state); given ``subjects`` instead (an explicit list), those;
        with neither, every Item (README §5, fixtures only). Then the units about the
        subjects and what a read of their recorded transitions needs:

        * every story whose detections name a subject, with all the Assertions on the story
          Item (its detections and the begin and end acts recorded there) (7.2.1, 7.6.7);
        * every expectation about a subject (6.1.1), found through the contexts of the
          Assertions about the subjects;
        * the extension records about a subject or naming one (10.4.2), and the acts that
          target the scope's Connections (8.6);
        * ``items``, for example a milestone named as the cutoff;
        * and, step by step until nothing is added: the acts that target, support, follow,
          correct or relocate to a loaded record, Item or story (``target_entries``), which
          brings reviews, reconciliations, ignores, withdrawals, corrections, supports, end
          acts and revisions; the records those acts name; the context Item of every loaded
          Assertion, the source Item of every statement and expectation, the Items an Item's
          definition names, and the publications of every milestone among them (4.4.1).

        No statement is loaded unless a loaded act names it. Reads that need a subject's
        statements (a story's disagreement, an expectation's standing that the recorded
        transitions do not settle) load them separately (``load_closure``)."""
        rs = RecordSet()
        candidates: set[str] | None = None
        if scope_id is not None:
            rs.connections = self.reach_connections(scope_id)
            candidates = {b for _a, b in rs.connections}
            subjects = candidates | {scope_id}
            # every Connection leaving the scope Item and its reach is loaded
            rs.out_complete |= subjects
        cl = _UnitsClosure(self, rs)
        cl.want_stories |= self.story_ids_about(subjects)
        cl.add_rows(self.expectation_rows_about(subjects, cl))
        cl.add_rows(self.extension_rows_about(subjects))
        if rs.connections:
            cl.add_rows(self._q(self._TARGETING, ([connection_entry(p) for p in sorted(rs.connections)],)))
        cl.want_items |= set(items)
        cl.run()
        return rs, candidates

    # -- normalizations (7.3.8, 9.10.1) ----------------------------------------------------

    # The predicate of the partial indexes assertions_normalization_idx and
    # assertions_normalization_scope_idx (reference/schema.sql), written identically so that the
    # planner answers the lookups from those indexes alone.
    _NORMALIZATION_COND = ('"values" ->> \'@action\' = \'reinterpret\' '
                           'OR "values" #>> \'{@corrected,@action}\' = \'reinterpret\'')
    # The scope Item a normalization names (its one Item target, 7.3.8), or that the replacement
    # content of a correction of one names: the expression of assertions_normalization_scope_idx
    _NORMALIZATION_SCOPE = ('coalesce("values" #>> \'{@corrected,@targets,0,id}\', '
                            '"values" #>> \'{@targets,0,id}\')')

    def normalization_rows(self) -> list:
        """Every normalization in the store (``@action: "reinterpret"``, 7.3.8) and every
        correction whose replacement content is one, from the partial index that holds only
        them. Used only where a read names no scope (fixtures only)."""
        return self._q(f"SELECT {self._A_COLS} FROM assertions WHERE {self._NORMALIZATION_COND}")

    def has_normalizations(self) -> bool:
        """Whether the store holds any normalization, from the partial index alone."""
        return bool(self._q(f"SELECT 1 FROM assertions WHERE {self._NORMALIZATION_COND} LIMIT 1"))

    def normalization_rows_for_scopes(self, ids: Iterable[str]) -> list:
        """The normalizations (7.3.8) whose scope Item is one of ``ids``, and the corrections
        whose replacement content is a normalization of one of them: one scan of the partial
        index assertions_normalization_scope_idx, which holds only them, keyed by the scope Item.
        Normalizations of other scopes are not read (9.10.1)."""
        ids = sorted(set(ids))
        if not ids:
            return []
        return self._q(f"SELECT {self._A_COLS} FROM assertions WHERE {self._NORMALIZATION_SCOPE} = ANY(%s::text[]) "
                       f"AND ({self._NORMALIZATION_COND})", (ids,))

    def ancestor_connections(self, ids: Iterable[str]) -> dict[tuple[str, str], dict]:
        """The Connections into the Items and into every Item from which they are reached
        backwards, in any state (2.1.5), in one recursive query: every path from a scope Item
        to one of the Items lies among them. Each step is one search of the index on
        ``to_id`` per Item, so the cost follows the Items and their ancestors, never the store."""
        ids = sorted(set(ids))
        if not ids:
            return {}
        rows = self._q(
            """WITH RECURSIVE up(id) AS (
                   SELECT unnest(%s::text[])
                   UNION
                   SELECT c.from_id FROM up r
                   CROSS JOIN LATERAL (SELECT from_id FROM connections WHERE to_id = r.id OFFSET 0) AS c)
               SELECT c.from_id, c.to_id, c.properties::text FROM up r
               CROSS JOIN LATERAL (SELECT * FROM connections WHERE to_id = r.id OFFSET 0) AS c""", (ids,))
        parsed = _Parsed()
        return {(r[0], r[1]): parsed(r[2]) for r in rows}

    def incoming_from_outside(self, ids: Iterable[str], known_from: Iterable[str]) -> dict[tuple[str, str], dict]:
        """The Connections into the Items ``ids`` from Items not in ``known_from``, the Items whose
        outgoing Connections are already loaded: one search of the index on ``to_id`` per Item,
        and only the Connections not already loaded are returned."""
        ids = sorted(set(ids))
        if not ids:
            return {}
        rows = self._q(
            "SELECT c.from_id, c.to_id, c.properties::text FROM unnest(%s::text[]) AS k(id) "
            "CROSS JOIN LATERAL (SELECT * FROM connections WHERE to_id = k.id OFFSET 0) AS c "
            "WHERE NOT EXISTS (SELECT 1 FROM unnest(%s::text[]) AS m(id) WHERE m.id = c.from_id)",
            (ids, sorted(set(known_from))))
        parsed = _Parsed()
        return {(r[0], r[1]): parsed(r[2]) for r in rows}

    def load_normalizations(self, rs: RecordSet, subjects: Iterable[str] | None, issuance: bool = False) -> bool:
        """Add to ``rs`` what the interpretation in force for the subjects needs (7.3.8): the
        normalizations whose scope Item is a subject or one of its ancestors, and the
        corrections of them, with their contexts and the scope Items they target; and, when
        there is any, the Connections into the subjects and their ancestors with the lifecycle
        acts and corrections that target them, since a normalization applies to an Item while it
        is a member of the normalization's scope (2.1.5). Normalizations of other scopes are not
        read (9.10.1). With ``issuance``, also the records of the communications that carry the
        normalizations, which a participant perspective reads (4.4.2, 4.6.1). Returns whether
        any normalization targets a subject or one of its ancestors. ``subjects`` None means
        every Item and every normalization (fixtures only).

        The Connections already in ``rs`` are used, not fetched again: the ancestors of the
        subjects among them are found in memory, and only the Connections into those Items from
        Items whose outgoing Connections are not loaded are fetched (for a scope's reach, the
        ones that enter it from outside), with the ancestors of their sources. The normalizations
        are then looked up by those scope Items in one scan of an index that holds only
        normalizations, so that a store whose normalizations are in other projects adds only
        that scan and the search for Connections entering the scope."""
        if rs.complete:
            return any(a.values.get("@action") == "reinterpret" or
                       (isinstance(a.values.get("@corrected"), dict) and a.values["@corrected"].get("@action") == "reinterpret")
                       for a in rs.assertions.values())
        if subjects is None:
            rows = self.normalization_rows()
            if not rows:
                return False
            conns = {(r[0], r[1]): from_json_text(r[2]) for r in self._q("SELECT from_id, to_id, properties::text FROM connections")}
        else:
            subjects = set(subjects)
            if subjects <= rs.no_normalization:
                return False
            if not self.has_normalizations():
                rs.no_normalization |= subjects
                return False
            # 2.1.5, 7.3.8: a normalization applies to a subject only while the subject is a
            # member of its scope, so its scope Item is the subject or one of its ancestors
            # through the Connections in any state; only those Items' normalizations are read
            subjects = set(subjects)
            into: dict[str, list[str]] = {}
            for a, b in rs.connections:
                into.setdefault(b, []).append(a)
            up = set(subjects)
            stack = list(subjects)
            while stack:
                n = stack.pop()
                for m in into.get(n, ()):
                    if m not in up:
                        up.add(m)
                        stack.append(m)
            if rs.out_complete:
                # a scope's reach is loaded: only the Connections entering it are fetched, with
                # the ancestors of the Items they come from
                entering = self.incoming_from_outside(up - rs.in_complete, rs.out_complete)
                outside = {a for a, _b in entering} - up
                conns = dict(entering)
                if outside:
                    conns.update(self.ancestor_connections(outside))
            else:
                # no Item's Connections are all loaded: every Connection into the Items and their
                # ancestors, in one recursive query
                conns = self.ancestor_connections(up - rs.in_complete)
                outside = {a for a, _b in conns} - up
            rows = self.normalization_rows_for_scopes(up | outside | {i for pair in conns for i in pair})
            if not rows:
                rs.no_normalization |= subjects
                return False
            # every Connection into the subjects, their ancestors and the Items entering them is
            # now loaded
            rs.in_complete |= up | outside | {i for pair in conns for i in pair}
        cl = _UnitsClosure(self, rs)
        cl.add_rows(rows)
        fresh = {p: v for p, v in conns.items() if p not in rs.connections}
        rs.connections.update(fresh)
        if fresh:
            cl.add_rows(self._q(self._TARGETING, ([connection_entry(p) for p in sorted(fresh)],)))
        cl.run()
        if issuance:
            sources = set()
            for r in rows:
                iss = from_json_text(r[3]).get("@issuance")
                if isinstance(iss, dict) and isinstance(iss.get("id"), str):
                    sources.add(r[2])
            if sources:
                self.load_closure(sources, rs, issuance=True)
        return True

    def story_ids_about(self, subjects: set[str] | None) -> set[str]:
        """The stories whose detections name one of the subjects in ``@story``, and those whose
        detection a correction replaces with content naming one (7.2.1, 8.3.1)."""
        det = "\"values\" ->> '@action' = 'detect'"
        cor = "\"values\" ->> '@action' = 'correct'"
        if subjects is None:
            rows = self._q(f"SELECT item_id FROM assertions WHERE {det} UNION "
                           f"SELECT \"values\" #>> '{{@targets,0,item}}' FROM assertions WHERE {cor} "
                           "AND \"values\" #>> '{@corrected,@story,subject,id}' IS NOT NULL")
        else:
            rows = self._q(
                "SELECT DISTINCT a.story FROM unnest(%s::text[]) AS k(id) CROSS JOIN LATERAL ("
                f"SELECT item_id AS story FROM assertions WHERE {det} AND \"values\" #>> '{{@story,subject,id}}' = k.id "
                f"UNION ALL SELECT \"values\" #>> '{{@targets,0,item}}' FROM assertions WHERE {cor} "
                "AND \"values\" #>> '{@corrected,@story,subject,id}' = k.id OFFSET 0) AS a", (sorted(subjects),))
        return {r[0] for r in rows if isinstance(r[0], str)}

    def expectation_rows_about(self, subjects: set[str] | None, cl: "_UnitsClosure") -> list:
        """The Assertions about the subjects at an expectation context (6.1.1). The contexts
        of the Assertions about the subjects are read first; those whose recorded role is
        ``expectation``, and those that an Item correction targets (8.3.8), are expectation
        contexts or may be. The context Items and their corrections are loaded into ``cl``."""
        if subjects is None:
            ctx = {r[0] for r in self._q("SELECT DISTINCT context_id FROM assertions")}
        else:
            ctx = {r[0] for r in self._q(
                "SELECT DISTINCT a.context_id FROM unnest(%s::text[]) AS k(id) CROSS JOIN LATERAL "
                "(SELECT context_id FROM assertions WHERE item_id = k.id OFFSET 0) AS a", (sorted(subjects),))}
        if not ctx:
            return []
        exp_ctx = set()
        for it in self.items(ctx):
            cl.add_item(it)
            if it.role == "expectation":
                exp_ctx.add(it.id)
        corrections = self._q(self._TARGETING, ([item_entry(c) for c in sorted(ctx)],))
        cl.searched |= {item_entry(c) for c in ctx}
        cl.add_rows(corrections)
        exp_ctx |= {t["id"] for r in corrections for t in act_targets(from_json_text(r[3]))
                    if t.get("@ref") == "item" and t.get("id") in ctx}
        if not exp_ctx:
            return []
        if subjects is None:
            return self._q(f"SELECT {self._A_COLS} FROM assertions WHERE context_id = ANY(%s)", (sorted(exp_ctx),))
        return self._q(f"SELECT {self._A_COLS_A} FROM unnest(%s::text[]) AS k(id) CROSS JOIN LATERAL "
                       "(SELECT * FROM assertions WHERE item_id = k.id AND context_id = ANY(%s) OFFSET 0) AS a",
                       (sorted(subjects), sorted(exp_ctx)))

    def extension_rows_about(self, subjects: set[str] | None) -> list:
        """The extension records (``extension_content``, 10.4.1) about the subjects or naming
        one in a reference, from the partial indexes that hold only such records (10.4.2)."""
        if subjects is None:
            return self._q(f'SELECT {self._A_COLS} FROM assertions WHERE extension_content("values")')
        return self._q(
            f"SELECT {self._A_COLS_A} FROM unnest(%s::text[]) AS k(id) CROSS JOIN LATERAL ("
            'SELECT * FROM assertions WHERE extension_content("values") AND item_id = k.id UNION ALL '
            'SELECT * FROM assertions WHERE extension_content("values") '
            "AND identifier_entries(\"values\") @> ARRAY['item:' || k.id] AND item_id <> k.id OFFSET 0) AS a",
            (sorted(subjects),))

    def load_statements_of(self, rs: RecordSet, pairs: Iterable[tuple[str, str]]) -> RecordSet:
        """Add to ``rs`` every Assertion by each source about each subject, and what reading
        them needs: the acts that target them (withdrawals, corrections) and so on, their
        contexts and the publications of those that are milestones. A source's position for
        a property (5.2.1, 6.7.4) reads exactly these (positions.classify)."""
        pairs = sorted(set(pairs))
        if not pairs:
            return rs
        cl = _UnitsClosure(self, rs)
        cl.add_rows(self._q(self._BY_SUBJECT_SOURCE, ([p[0] for p in pairs], [p[1] for p in pairs])))
        cl.run()
        return rs


class _UnitsClosure:
    """The step-by-step loading of ``Store.load_listing``. Records and Items are added to a
    record set; each round fetches what the previous one asked for, follows the new records'
    references and finds the acts that target the new records, Items and stories."""

    def __init__(self, store: Store, rs: RecordSet) -> None:
        self.store = store
        self.rs = rs
        self.want_stories: set[str] = set()
        self.want_triples: set[Triple] = set()
        self.want_items: set[str] = set()
        self.want_pubs: set[str] = set()
        self.done_stories: set[str] = set()
        self.done_triples: set[Triple] = set()
        self.done_items: set[str] = set(rs.items)
        self.done_pubs: set[str] = set()
        self.searched: set[str] = set()
        self.fresh: list[RawAssertion] = []
        self.fresh_items: list[Item] = []
        self.keys: list[str] = []

    def add_rows(self, rows) -> None:
        for r in rows:
            t = (r[0], r[1], r[2])
            if t in self.rs.assertions:
                continue
            a = Store._assertion(r)
            self.rs.assertions[t] = a
            self.fresh.append(a)

    def add_item(self, it: Item) -> None:
        if it.id in self.rs.items:
            return
        self.rs.items[it.id] = it
        self.done_items.add(it.id)
        self.fresh_items.append(it)

    def _follow(self, a: RawAssertion) -> None:
        v, t = a.values, a.triple
        self.want_items.add(t[1])
        if "@action" not in v:
            self.want_items.add(t[2])
        if v.get("@action") == "detect":
            self.want_stories.add(t[0])
        for ref in act_targets(v):
            self._want_ref(ref, v.get("@action") == "correct")
        after = v.get("@after")
        if isinstance(after, dict):
            self._want_ref(after, False)
        for key in ("@representative", "@successor"):
            r = v.get(key)
            if isinstance(r, dict) and r.get("@ref") == "item" and isinstance(r.get("id"), str):
                self.want_stories.add(r["id"])
        corrected = v.get("@corrected")
        for ref in iter_refs(corrected):
            self._want_ref(ref, False)
        if isinstance(corrected, dict) and corrected.get("@action") == "detect":
            for ref in act_targets(v):
                if ref.get("@ref") == "assertion" and isinstance(ref.get("item"), str):
                    self.want_stories.add(ref["item"])
        for ref in ref_list(v, "@basis"):
            if ref.get("@ref") == "assertion" and isinstance(ref.get("context"), str):
                self.want_items.add(ref["context"])

    def _want_ref(self, ref: dict, correction: bool) -> None:
        kind = ref.get("@ref")
        if kind == "assertion":
            t = tuple(ref.get(k) for k in ("item", "context", "source"))
            if all(isinstance(x, str) for x in t):
                self.want_triples.add(t)
            sup = ref.get("support")
            if isinstance(sup, dict):
                self._want_ref(sup, False)
        elif kind == "item" and isinstance(ref.get("id"), str):
            # an act targeting an Item: a story's acts, or an Item correction (8.3.8), which
            # can change the Item's role, so its publications are loaded too
            self.want_items.add(ref["id"])
            self.want_stories.add(ref["id"])
            if correction:
                self.want_pubs.add(ref["id"])

    def run(self) -> None:
        st = self.store
        while True:
            stories = sorted(self.want_stories - self.done_stories)
            self.done_stories |= set(stories)
            if stories:
                self.add_rows(st._q(st._BY_ITEM, (stories,)))
                self.keys += [item_entry(s) for s in stories]
            triples = sorted(t for t in self.want_triples - self.done_triples if t not in self.rs.assertions)
            self.done_triples |= set(triples)
            if triples:
                self.add_rows(st._q(st._BY_TRIPLE, ([t[0] for t in triples], [t[1] for t in triples],
                                                    [t[2] for t in triples])))
            items = sorted(self.want_items - self.done_items)
            self.done_items |= set(items)
            for it in st.items(items):
                self.add_item(it)
            for it in self.fresh_items:
                self.keys.append(item_entry(it.id))
                for i in definition_item_ids(it.definition):
                    if i not in self.done_items:
                        self.want_items.add(i)
                if it.role == "milestone":
                    self.want_pubs.add(it.id)
            self.fresh_items = []
            pubs = sorted(self.want_pubs - self.done_pubs)
            self.done_pubs |= set(pubs)
            if pubs:
                self.add_rows(st._q(st._BY_SELF_CONTEXT, (pubs,)))
            fresh, self.fresh = self.fresh, []
            for a in fresh:
                self._follow(a)
                self.keys.append(assertion_entry(a.triple))
            keys = sorted(set(self.keys) - self.searched)
            self.keys = []
            self.searched |= set(keys)
            if keys:
                self.add_rows(st._q(st._TARGETING, (keys,)))
            pending = (self.want_stories - self.done_stories) or (self.want_items - self.done_items) \
                or (self.want_pubs - self.done_pubs) \
                or {t for t in self.want_triples - self.done_triples if t not in self.rs.assertions}
            if not self.fresh and not self.fresh_items and not pending:
                return
