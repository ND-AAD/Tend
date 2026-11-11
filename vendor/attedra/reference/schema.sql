-- Attedra 0.1.0 (preliminary): reference schema.
-- Three tables only (spec I-1). Storage-level identity: triple uniqueness (2.3.2, I-2)
-- and one Connection per ordered pair (2.2.1, I-4). No ON DELETE CASCADE: the only
-- deletion is confirmed removal (8.5), executed by the library in one transaction.

CREATE TABLE items (
    id          text PRIMARY KEY,
    kind        text NOT NULL,
    label       text,
    definition  jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (jsonb_typeof(definition) = 'object')
);

CREATE TABLE connections (
    from_id     text NOT NULL REFERENCES items (id),
    to_id       text NOT NULL REFERENCES items (id),
    properties  jsonb NOT NULL,
    PRIMARY KEY (from_id, to_id),
    CHECK (jsonb_typeof(properties) = 'object')
);

CREATE TABLE assertions (
    item_id     text NOT NULL REFERENCES items (id),
    context_id  text NOT NULL REFERENCES items (id),
    source_id   text NOT NULL REFERENCES items (id),
    "values"    jsonb NOT NULL,
    recorded_at timestamptz,
    recorded_by text,
    PRIMARY KEY (item_id, context_id, source_id),
    CHECK (jsonb_typeof("values") = 'object')
);

-- Implementation indexes (reference mechanism, not model requirements). The GIN
-- indexes have fastupdate off. With it on, new entries wait in a pending list that every
-- search reads in full, and its length depends on how much was written since the last
-- vacuum, not on the read.
CREATE INDEX assertions_source_idx  ON assertions (source_id);
CREATE INDEX assertions_context_idx ON assertions (context_id);
CREATE INDEX assertions_values_gin  ON assertions USING gin ("values" jsonb_path_ops) WITH (fastupdate = off);
CREATE INDEX connections_to_idx     ON connections (to_id);

-- Reference discovery (spec 2.4.5, 9.10.1). A reference names records by the
-- string values of its identifier members (2.4.1-2.4.2): id, item, from and to name the
-- Item a reference is to, is about or connects; context and source are an Assertion
-- reference's other coordinates. identifier_entries(doc) returns one entry for every such
-- member holding a string, in every object at any depth of doc: 'item:' followed by the
-- string for id, item, from and to, and 'context:' or 'source:' followed by the string for
-- the other two. Repeats are kept and the order has no meaning. It depends only on its
-- argument and compares member names bytewise (COLLATE "C"), so it is IMMUTABLE. Its COST
-- states that one call costs about as much as a thousand simple operators, as measured in
-- the reference environment, so that the planner does not prefer evaluating it on every
-- row. The two GIN indexes over it find the records that hold any of a set of entries; the
-- library applies the exact reference test to those records. Function and indexes are
-- derived from stored values and add no table, column or coordinate (I-1).
CREATE FUNCTION identifier_entries(doc jsonb) RETURNS text[]
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE COST 1000
    RETURN ARRAY(
        SELECT CASE WHEN m.key COLLATE "C" IN ('context', 'source') THEN m.key ELSE 'item' END
               || ':' || (m.value #>> '{}')
        FROM jsonb_path_query(doc, 'strict $.** ? (@.type() == "object")') AS o(obj)
        CROSS JOIN LATERAL jsonb_each(o.obj) AS m
        WHERE m.key COLLATE "C" IN ('id', 'item', 'from', 'to', 'context', 'source')
          AND jsonb_typeof(m.value) = 'string');

CREATE INDEX assertions_identifiers_gin ON assertions USING gin (identifier_entries("values")) WITH (fastupdate = off);
CREATE INDEX items_identifiers_gin      ON items USING gin (identifier_entries(definition)) WITH (fastupdate = off);

-- Loading by discovery (spec 2.4.5, 9.10.1; store.discovered_item_ids). discovery_entries(doc)
-- returns the strings held at the positions through which an act references a record about an
-- Item: the item, id, from and to members of the references in @targets, @basis, @establishes,
-- @reaffirms, @after, @relates_to, @successor, @representative and @issuance, the item of a
-- support selector in @targets, the item of the references in @corrected and in its members of
-- those names, the subject id of @story, and the prior and new items of @transitions. It is
-- evaluated in lax mode, so it returns every string store.discovered_item_ids returns and may
-- return more (a member holding one object where a list is expected, a list where one object
-- is expected); the library keeps only the records the exact test selects. A participant, a
-- frame, a distribution list or a domain value names an Item without being a discovery
-- position, so the records naming an Item there are not among the entries for it. The strings
-- at the @issuance positions are prefixed with U+001E, so that a load may leave out the acts
-- that name an Item only as the communication carrying them (store.Store.load_closure).
CREATE FUNCTION discovery_entries(doc jsonb) RETURNS text[]
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE COST 1000
    RETURN ARRAY(
        SELECT p.mark || (n.ref ->> m.key)
        FROM (VALUES ('lax $."@targets"[*]'::jsonpath, ''), ('lax $."@basis"[*]', ''),
                     ('lax $."@establishes"[*]', ''), ('lax $."@reaffirms"[*]', ''), ('lax $."@after"', ''),
                     ('lax $."@relates_to"', ''), ('lax $."@successor"', ''), ('lax $."@representative"', ''),
                     ('lax $."@issuance"', E'\x1e')) AS p(path, mark)
        CROSS JOIN LATERAL jsonb_path_query(doc, p.path) AS n(ref)
        CROSS JOIN (VALUES ('item'), ('id'), ('from'), ('to')) AS m(key)
        WHERE jsonb_typeof(n.ref -> m.key) = 'string'
        UNION ALL
        SELECT p.mark || (v.leaf #>> '{}')
        FROM (VALUES ('lax $."@corrected"."@targets"[*]."item"'::jsonpath, ''),
                     ('lax $."@corrected"."@basis"[*]."item"', ''), ('lax $."@corrected"."@establishes"[*]."item"', ''),
                     ('lax $."@corrected"."@reaffirms"[*]."item"', ''), ('lax $."@targets"[*]."support"."item"', ''),
                     ('lax $."@corrected"."@after"."item"', ''), ('lax $."@corrected"."@relates_to"."item"', ''),
                     ('lax $."@corrected"."@successor"."item"', ''), ('lax $."@corrected"."@representative"."item"', ''),
                     ('lax $."@corrected"."@issuance"."item"', E'\x1e'), ('lax $."@corrected"."item"', ''),
                     ('lax $."@story"."subject"."id"', ''), ('lax $."@transitions"[*]."prior"."item"', ''),
                     ('lax $."@transitions"[*]."new"."item"', '')) AS p(path, mark)
        CROSS JOIN LATERAL jsonb_path_query(doc, p.path) AS v(leaf)
        WHERE jsonb_typeof(v.leaf) = 'string');

CREATE INDEX assertions_discovery_gin ON assertions USING gin (discovery_entries("values")) WITH (fastupdate = off);

-- Acts by their targets (spec 7.6.7: reads find acts by their target; 7.6.14, 9.10.1). Used by
-- the record-perspective listing reads, which load the records of the units in scope and,
-- step by step, the acts that target them. target_entries(doc) returns one entry for every
-- reference in @targets (and the support selected inside one), @establishes, @reaffirms and
-- @after, and for every reference at any depth of @corrected: 'a' and the Assertion's item,
-- context and source, 'i' and an Item's id, or 'c' and a Connection's from and to, the parts
-- separated by the unit separator (U+001F). A record that targets, supports, follows,
-- corrects or relocates to a record therefore holds that record's entry. Selectors and the
-- other members of a reference are not part of it; the library applies the exact test.
CREATE FUNCTION target_entries(doc jsonb) RETURNS text[]
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE COST 1000
    RETURN ARRAY(
        SELECT x.entry FROM (
            SELECT CASE r.ref ->> '@ref' COLLATE "C"
                       WHEN 'assertion' THEN 'a' || (r.ref ->> 'item') || E'\x1f' || (r.ref ->> 'context')
                                                 || E'\x1f' || (r.ref ->> 'source')
                       WHEN 'item' THEN 'i' || (r.ref ->> 'id')
                       WHEN 'connection' THEN 'c' || (r.ref ->> 'from') || E'\x1f' || (r.ref ->> 'to')
                   END AS entry
            FROM unnest('{"lax $.\"@targets\"[*]", "lax $.\"@targets\"[*].\"support\"", "lax $.\"@establishes\"[*]",
                          "lax $.\"@reaffirms\"[*]", "lax $.\"@after\"",
                          "lax $.\"@corrected\".** ? (@.type() == \"object\")"}'::jsonpath[]) AS p(path)
            CROSS JOIN LATERAL jsonb_path_query(doc, p.path) AS r(ref)
            WHERE jsonb_typeof(r.ref) = 'object') AS x
        WHERE x.entry IS NOT NULL);

CREATE INDEX assertions_targets_gin ON assertions USING gin (target_entries("values")) WITH (fastupdate = off);

-- Stories by subject (spec 7.2.1, 9.5.3, 9.5.7): the detections naming a subject in @story,
-- and the corrections whose replacement content names one.
CREATE INDEX assertions_story_subject_idx ON assertions (("values" #>> '{@story,subject,id}'))
    WHERE "values" ->> '@action' = 'detect';
CREATE INDEX assertions_corrected_story_subject_idx ON assertions (("values" #>> '{@corrected,@story,subject,id}'))
    WHERE "values" ->> '@action' = 'correct';

-- Normalizations (spec 7.3.8, 9.10.1): the normalization acts (`@action: "reinterpret"`) and the
-- corrections whose replacement content is one. The partial index holds only them, so a store
-- with none answers the lookup without reading any other record (store.Store.has_normalizations).
-- The normalizations that apply to an Item are found by their scope Items, the Item and its
-- ancestors, through assertions_normalization_scope_idx below, never by traversing the store.
CREATE INDEX assertions_normalization_idx ON assertions (item_id)
    WHERE "values" ->> '@action' = 'reinterpret' OR "values" #>> '{@corrected,@action}' = 'reinterpret';
-- The same records keyed by the scope Item they name: a normalization's one Item target, or that
-- of the normalization a correction's replacement content is. A read or a write looks the
-- normalizations of its subjects' scopes up in one scan of this index, with the subjects and
-- their ancestors as keys (store.Store.normalization_rows_for_scopes), so that the normalizations
-- of other scopes are not read and the number of keys costs no search of any other index.
CREATE INDEX assertions_normalization_scope_idx ON assertions
    ((coalesce("values" #>> '{@corrected,@targets,0,id}', "values" #>> '{@targets,0,id}')))
    WHERE "values" ->> '@action' = 'reinterpret' OR "values" #>> '{@corrected,@action}' = 'reinterpret';

-- Extension content (spec 10.4.1, 10.4.2; conformance README §5, *Side reports*): an Assertion
-- with an @action this specification does not define, a correction whose replacement content
-- has one, or a record carrying a member beginning with @ that 2.4.4 does not define, in an
-- object at any depth. The lists are those of model.ACTIONS and model.DEFINED_VALUE_MEMBERS.
-- The partial indexes hold only these records, so a read finds the ones about its subjects, or
-- naming them, without reading the others.
CREATE FUNCTION extension_content(doc jsonb) RETURNS boolean
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    RETURN coalesce((doc ? '@action'
            AND NOT (jsonb_typeof(doc -> '@action') = 'string'
                     AND (doc ->> '@action') COLLATE "C" IN ('begin', 'correct', 'detect', 'disconnect', 'end',
                         'establish', 'ignore', 'reaffirm', 'reconcile', 'reconnect', 'reinterpret', 'review',
                         'withdraw')))
        OR (coalesce(jsonb_typeof(doc -> '@corrected') = 'object', false) AND (doc -> '@corrected') ? '@action'
            AND NOT (jsonb_typeof(doc #> '{@corrected,@action}') = 'string'
                     AND (doc #>> '{@corrected,@action}') COLLATE "C" IN ('begin', 'correct', 'detect', 'disconnect',
                         'end', 'establish', 'ignore', 'reaffirm', 'reconcile', 'reconnect', 'reinterpret', 'review',
                         'withdraw')))
        OR doc @? 'strict $.** ? (@.type() == "object").keyvalue() ? (@.key starts with "@" && !(@.key == "@ref"
            || @.key == "@action" || @.key == "@targets" || @.key == "@basis" || @.key == "@party" || @.key == "@outcome"
            || @.key == "@corrected" || @.key == "@effective" || @.key == "@establishes" || @.key == "@reaffirms"
            || @.key == "@frame" || @.key == "@story" || @.key == "@transitions" || @.key == "@relates_to"
            || @.key == "@successor" || @.key == "@representative" || @.key == "@until" || @.key == "@producer"
            || @.key == "@agent" || @.key == "@distribution" || @.key == "@issuance" || @.key == "@published"
            || @.key == "@eligible" || @.key == "@ask" || @.key == "@suggested" || @.key == "@after"
            || @.key == "@context" || @.key == "@eligibility" || @.key == "@period"
            || @.key == "@interpretation")).key', false);

CREATE INDEX assertions_extension_item_idx ON assertions (item_id) WHERE extension_content("values");
CREATE INDEX assertions_extension_identifiers_gin ON assertions USING gin (identifier_entries("values"))
    WITH (fastupdate = off) WHERE extension_content("values");

-- Declared extension (spec 10.4.4, 10.3; conformance README §5, *Declared extension*). While
-- any record carries the member @x-fixture-refs, a removal plan for an Item is refused. These
-- partial indexes hold only the records that carry it in an object at any depth, so the check
-- (Store.declared_extension_in_store) reads none of the others. Their predicate is the
-- condition that check writes; they add no table, column or coordinate (I-1).
CREATE INDEX assertions_declared_extension_idx ON assertions (item_id)
    WHERE "values" @? '$.** ? (exists (@."@x-fixture-refs"))';
CREATE INDEX items_declared_extension_idx      ON items (id)
    WHERE definition @? '$.** ? (exists (@."@x-fixture-refs"))';
