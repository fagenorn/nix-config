"""The reply schema subset, and the one validator for it (#1525).

An agent step's reply schema is held to a small subset so that the engine and the Claude client
read it the same way and the engine carries no schema library. `engine check` (`schema_problem`)
and the shell (`reply_problem`) both use this module, so the checker admits exactly what the shell validates.

The subset. The root is an object node. A node is one of:

- `{"type": "string"}`, `{"type": "integer"}` or `{"type": "boolean"}` (exactly the key `type`);
  an integer node takes any integral number, so `2.0` conforms and `true` does not;
- `{"enum": [...]}`, optionally with `"type": "string"`: a non-empty list of distinct strings;
- `{"type": "array", "items": <node>}` (exactly those keys);
- `{"type": "object", "properties": {<name>: <node>}, "additionalProperties": false}` with an
  optional `required` list of distinct strings that are each a property. An object is closed:
  `additionalProperties: false` is required, and a member outside `properties` is a problem.

Anything else (`number`, `null`, a type list, `const`, `oneOf`, `$ref`, `description`,
`pattern`, ...) is outside the subset. `reply_problem` fails closed on such a node: it
returns a problem, never `None`.

The engine blanks a finding's rule id that no standards layer defines when it stores the reply:
`cites_rules` says whether a reply cites any rule and `without_unknown_rules` is the
reply with each unknown id set to `""`. This module imports nothing from the engine.
"""

from __future__ import annotations

from typing import Collection, Mapping

_SCALARS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: (isinstance(v, int) and not isinstance(v, bool))
    or (isinstance(v, float) and v.is_integer()),
    "boolean": lambda v: isinstance(v, bool),
}
_OBJECT_KEYS = {"type", "properties", "required", "additionalProperties"}


def schema_problem(schema: object, where: str = "reply") -> str | None:
    """None when `schema` is a subset object node, else the first construct outside it."""
    if isinstance(schema, dict) and ("enum" in schema or schema.get("type") != "object"):
        return f"a root that is not an object node at {where}"
    return _node_problem(schema, where)


def reply_problem(schema: Mapping, value: object, where: str = "reply") -> str | None:
    """None when `value` conforms to the subset `schema`, else the first way it does not."""
    problem = schema_problem(schema, where)
    if problem:
        return f"the schema uses {problem}"
    return _value_problem(schema, value, where)


def cites_rules(reply: object) -> bool:
    """True when `reply` has a finding whose `rule` is a non-empty string."""
    findings = reply.get("findings") if isinstance(reply, dict) else None
    return isinstance(findings, list) and any(
        isinstance(f, dict) and isinstance(f.get("rule"), str) and f["rule"] != "" for f in findings)


def without_unknown_rules(reply: Mapping, known: Collection[str]) -> dict:
    """A copy of `reply` whose findings' `rule` strings outside `known` are blank; `reply` is not mutated."""
    findings = reply.get("findings")
    if not isinstance(findings, list):
        return dict(reply)
    return {**reply, "findings": [
        {**f, "rule": ""} if isinstance(f, dict) and isinstance(f.get("rule"), str) and f["rule"] not in known else f
        for f in findings]}


def _enum_problem(node: dict, where: str) -> str | None:
    if set(node) - {"enum", "type"}:
        key = sorted(set(node) - {"enum", "type"})[0]
        return f"the keyword '{key}' at {where}"
    enum = node["enum"]
    if (not isinstance(enum, list) or not enum or not all(isinstance(v, str) for v in enum)
            or len(set(enum)) != len(enum)):
        return f"an enum that is not a non-empty list of distinct strings at {where}"
    if "type" in node and node["type"] != "string":
        return f"an enum whose type is not string at {where}"
    return None


def _node_problem(node: object, where: str) -> str | None:
    if not isinstance(node, dict):
        return f"a node that is not an object at {where}"
    if "enum" in node:
        return _enum_problem(node, where)
    kind = node.get("type")
    if isinstance(kind, list):
        return f"a type list at {where}"
    if not isinstance(kind, str):
        if "type" in node:
            return f"the type {kind!r} at {where}"
        return f"the keyword '{sorted(node)[0]}' at {where}" if node else f"a node with no type at {where}"
    if kind in _SCALARS:
        allowed = {"type"}
    elif kind == "array":
        allowed = {"type", "items"}
    elif kind == "object":
        allowed = _OBJECT_KEYS
    else:
        return f"the type {kind!r} at {where}"
    for key in sorted(set(node) - allowed):
        return f"the keyword '{key}' at {where}"
    if kind == "array":
        if "items" not in node:
            return f"an array with no items at {where}"
        return _node_problem(node["items"], f"{where}.items")
    if kind == "object":
        return _object_problem(node, where)
    return None


def _object_problem(node: dict, where: str) -> str | None:
    if node.get("additionalProperties", True) is not False:
        return f"an object with no additionalProperties false at {where}"
    properties = node.get("properties")
    if not isinstance(properties, dict):
        return f"an object with no properties object at {where}"
    required = node.get("required", [])
    if (not isinstance(required, list) or not all(isinstance(n, str) for n in required)
            or len(set(required)) != len(required)):
        return f"a required list that is not distinct strings at {where}"
    for name in required:
        if name not in properties:
            return f"a required member '{name}' that is not a property at {where}"
    for name, child in properties.items():
        problem = _node_problem(child, f"{where}.properties.{name}")
        if problem:
            return problem
    return None


def _value_problem(node: Mapping, value: object, where: str) -> str | None:
    if "enum" in node:
        if not (isinstance(value, str) and value in node["enum"]):
            return f"{where} is {value!r}, not one of {node['enum']}"
        return None
    kind = node["type"]
    if kind in _SCALARS:
        return None if _SCALARS[kind](value) else f"{where} is not of type {kind}"
    if kind == "array":
        if not isinstance(value, list):
            return f"{where} is not of type array"
        for index, item in enumerate(value):
            problem = _value_problem(node["items"], item, f"{where}[{index}]")
            if problem:
                return problem
        return None
    if not isinstance(value, dict):
        return f"{where} is not of type object"
    for name in node.get("required", ()):
        if name not in value:
            return f"{where} lacks the required {name!r}"
    for name, member in value.items():
        if name not in node["properties"]:
            return f"{where} has the member {name!r} the schema does not allow"
        problem = _value_problem(node["properties"][name], member, f"{where}.{name}")
        if problem:
            return problem
    return None
