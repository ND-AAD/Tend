"""The value space (spec §5.1, 5.3, 5.5.1) and the reference forms (spec 2.4).

* Parsing JSON text with duplicate-key detection (5.1.1) and exact decimals (5.1.2).
* Normalization of ``""`` to ``null`` at any depth except inside reference objects (5.3.2).
* Literal, typed comparison (5.5.1), with references equal when they identify the same
  record.
* Reference discovery (2.4.5): every object carrying ``@ref``, found recursively.
* The compact reference strings of the conformance contract (README §4).
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

from .errors import WriteError

# 5.1.2: a fixed, portable bound of 34 significant digits and exponents between -999 and +999.
# Numbers within it are stored exactly; numbers outside it are rejected (10.2.4).
MAX_DIGITS = 34
MIN_EXPONENT = -999
MAX_EXPONENT = 999


# ---------------------------------------------------------------------------------------
# Parsing and serialization


def _pairs_hook(pairs):
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise WriteError("duplicate_key", f"duplicate key {key!r} in an object (5.1.1)")
        out[key] = value
    return out


def _reject_constant(name):
    raise WriteError("number_out_of_range", f"{name} is not an exact decimal number (5.1.2)")


def _parse_int(text: str):
    try:
        return int(text)
    except ValueError:  # beyond Python's integer-string limit: certainly beyond 5.1.2
        raise WriteError("number_out_of_range", "number has too many digits (5.1.2)") from None


def parse_json_text(text: str) -> Any:
    """Parse JSON text exactly: duplicate keys are rejected (5.1.1), decimals stay exact
    (5.1.2), and every number is checked against the supported bound."""
    if not isinstance(text, str):
        raise WriteError("10.2.4", "values must be JSON text")
    try:
        value = json.loads(text, object_pairs_hook=_pairs_hook, parse_float=Decimal,
                           parse_int=_parse_int, parse_constant=_reject_constant)
    except WriteError:
        raise
    except (ValueError, InvalidOperation) as e:
        raise WriteError("10.2.4", f"values are not valid JSON text: {e}") from None
    check_numbers(value)
    return value


def number_in_range(n) -> bool:
    """True when ``n`` is an exact decimal within 5.1.2: at most 34 significant digits and an
    exponent (scientific notation) between -999 and +999."""
    if isinstance(n, bool):
        return True
    d = Decimal(n) if isinstance(n, int) else n
    if not isinstance(d, Decimal) or not d.is_finite():
        return False
    if d == 0:
        return True
    sign, digits, exp = d.as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exp += 1
    while len(digits) > 1 and digits[0] == 0:
        digits.pop(0)
    if len(digits) > MAX_DIGITS:
        return False
    adjusted = exp + len(digits) - 1
    return MIN_EXPONENT <= adjusted <= MAX_EXPONENT


def check_numbers(value: Any) -> None:
    """Reject any number outside 5.1.2, at any depth (10.2.4)."""
    if isinstance(value, dict):
        for v in value.values():
            check_numbers(v)
    elif isinstance(value, list):
        for v in value:
            check_numbers(v)
    elif isinstance(value, float):
        raise WriteError("number_out_of_range", "binary floating point is not an exact decimal (5.1.2)")
    elif isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        if not number_in_range(value):
            raise WriteError("number_out_of_range", f"number {value} is outside the supported range (5.1.2)")


def to_json_text(value: Any) -> str:
    """Serialize a value to JSON text, writing decimals exactly (5.1.3)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite decimal")
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + to_json_text(v)
                              for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(to_json_text(v) for v in value) + "]"
    raise TypeError(f"not a JSON value: {value!r}")


_STORED_DECODER = json.JSONDecoder(parse_float=Decimal)


def from_json_text(text: str) -> Any:
    """Parse stored JSON text (already validated on write)."""
    return _STORED_DECODER.decode(text)


def to_result(value: Any) -> Any:
    """Convert an internal value to the plain JSON form returned by reads. Integral decimals
    become exact Python ints; other decimals become floats when the float spells the same
    decimal, and stay Decimal otherwise (see the report on the runner's serializer)."""
    if isinstance(value, dict):
        return {k: to_result(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_result(v) for v in value]
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        f = float(value)
        if Decimal(repr(f)) == value:
            return f
        return value
    return value


# ---------------------------------------------------------------------------------------
# Normalization (5.3.2)


def normalize(value: Any) -> Any:
    """Normalize ``""`` to ``null`` at any depth of a value, except inside reference objects
    (5.3.2). Nothing else is empty by implication."""
    if isinstance(value, str):
        return None if value == "" else value
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        if "@ref" in value:
            return value
        return {k: normalize(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------------------
# References (2.4)


def is_ref(value: Any) -> bool:
    return isinstance(value, dict) and "@ref" in value


def is_assertion_ref(value: Any) -> bool:
    return is_ref(value) and value.get("@ref") == "assertion"


def is_item_ref(value: Any) -> bool:
    return is_ref(value) and value.get("@ref") == "item"


def is_connection_ref(value: Any) -> bool:
    return is_ref(value) and value.get("@ref") == "connection"


def is_artifact_ref(value: Any) -> bool:
    return is_ref(value) and value.get("@ref") == "artifact"


def ref_triple(ref: dict) -> tuple[str, str, str]:
    return (ref["item"], ref["context"], ref["source"])


def iter_refs(value: Any) -> Iterator[dict]:
    """Every reference object in a value, recursively (2.4.5), including references nested
    inside references (a ``support`` selector)."""
    if isinstance(value, dict):
        if "@ref" in value:
            yield value
        for v in value.values():
            yield from iter_refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from iter_refs(v)


def ref_item_ids(ref: dict) -> set[str]:
    """Item ids that a reference names (used to follow references when loading)."""
    kind = ref.get("@ref")
    if kind == "assertion":
        return {x for x in (ref.get("item"), ref.get("context"), ref.get("source")) if isinstance(x, str)}
    if kind == "item":
        return {ref["id"]} if isinstance(ref.get("id"), str) else set()
    if kind == "connection":
        return {x for x in (ref.get("from"), ref.get("to")) if isinstance(x, str)}
    return set()


def ref_identity(ref: dict) -> tuple:
    """What a reference identifies; references are equal when this is equal (5.5.1)."""
    kind = ref.get("@ref")
    if kind == "assertion":
        sup = ref.get("support")
        return ("assertion", ref.get("item"), ref.get("context"), ref.get("source"),
                ref.get("property"), ref_identity(sup) if is_ref(sup) else None)
    if kind == "item":
        return ("item", ref.get("id"))
    if kind == "connection":
        return ("connection", ref.get("from"), ref.get("to"))
    if kind == "artifact":
        return ("artifact", ref.get("id"), ref.get("edition"))
    return ("ref", kind, canonical(dict((k, v) for k, v in ref.items() if k != "@ref")))


def assertion_ref(triple: tuple[str, str, str], prop: str | None = None) -> dict:
    ref = {"@ref": "assertion", "item": triple[0], "context": triple[1], "source": triple[2]}
    if prop is not None:
        ref["property"] = prop
    return ref


def item_ref(item_id: str) -> dict:
    return {"@ref": "item", "id": item_id}


# Compact forms (conformance README §4) ---------------------------------------------------


def compact(triple: tuple[str, str, str], prop: str | None = None) -> str:
    s = f"{triple[0]}|{triple[1]}|{triple[2]}"
    return s + (f"#{prop}" if prop is not None else "")


def compact_ref(ref: dict) -> str:
    """The compact string of a reference object."""
    kind = ref.get("@ref")
    if kind == "assertion":
        s = f"{ref['item']}|{ref['context']}|{ref['source']}"
        if is_ref(ref.get("support")):
            s += "^support:" + compact_ref(ref["support"])
            if ref.get("property") is not None:
                s += f"#{ref['property']}"
            return s
        if ref.get("property") is not None:
            s += f"#{ref['property']}"
        return s
    if kind == "item":
        return ref["id"]
    if kind == "connection":
        return f"{ref['from']}->{ref['to']}"
    if kind == "artifact":
        return f"artifact:{ref.get('id')}@{ref.get('edition')}"
    return json.dumps(ref)


def parse_compact(text: str) -> dict:
    """Parse a compact reference string into a reference object. ``a|b|c`` is an Assertion,
    ``a->b`` a Connection and a bare id an Item."""
    if "^support:" in text:
        left, right = text.split("^support:", 1)
        prop = None
        if "#" in right:
            right, prop = right.split("#", 1)
        ref = parse_compact(left)
        ref["support"] = parse_compact(right)
        if prop is not None:
            ref["property"] = prop
        return ref
    if "|" in text:
        prop = None
        body = text
        if "#" in body:
            body, prop = body.split("#", 1)
        parts = body.split("|")
        if len(parts) != 3:
            raise ValueError(f"not an assertion reference: {text!r}")
        ref = {"@ref": "assertion", "item": parts[0], "context": parts[1], "source": parts[2]}
        if prop is not None:
            ref["property"] = prop
        return ref
    if "->" in text:
        a, b = text.split("->", 1)
        return {"@ref": "connection", "from": a, "to": b}
    return {"@ref": "item", "id": text}


# ---------------------------------------------------------------------------------------
# Comparison (5.5.1)


def _num_key(n) -> tuple:
    d = Decimal(n) if isinstance(n, int) else n
    if d == 0:
        return ("n", 0, (), 0)
    sign, digits, exp = d.as_tuple()
    digits = list(digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exp += 1
    while digits and digits[0] == 0:
        digits.pop(0)
    return ("n", sign, tuple(digits), exp)


def canonical(value: Any) -> tuple:
    """A hashable canonical form under literal comparison (5.5.1): strings by identity,
    numbers by decimal value, arrays in order with multiplicity, objects by key set in any
    order, references by what they identify. Values of different types never coincide."""
    if value is None:
        return ("null",)
    if value is True or value is False:
        return ("b", value)
    if isinstance(value, str):
        return ("s", value)
    if isinstance(value, (int, Decimal)):
        return _num_key(value)
    if isinstance(value, float):
        return _num_key(Decimal(repr(value)))
    if isinstance(value, list):
        return ("a", tuple(canonical(v) for v in value))
    if isinstance(value, dict):
        if "@ref" in value:
            return ("r", ref_identity(value))
        return ("o", tuple(sorted((k, canonical(v)) for k, v in value.items())))
    raise TypeError(f"not a JSON value: {value!r}")


def literal_equal(a: Any, b: Any) -> bool:
    """The default literal, typed comparison (5.5.1). No conversions are inferred (5.5.2)."""
    return canonical(a) == canonical(b)


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, Decimal, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def is_reserved_key(key: str) -> bool:
    return isinstance(key, str) and key.startswith("@")


def properties_of(values: dict) -> dict:
    """The named properties of an Assertion's values: every key that is not reserved
    (2.4.7, 5.2.4)."""
    return {k: v for k, v in values.items() if not is_reserved_key(k)}
