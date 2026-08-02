"""diff(baseline, current) -> findings, with fixed severities.

Severity is plain code, never a model's judgement, so the same drift always
gets the same severity and a CI gate built on ``--fail-on`` is stable. The LLM
may later write an explanation *on top of* a finding; it never assigns one.
"""

from .models import Finding

BREAKING = "breaking"
WARNING = "warning"
INFO = "info"

_ORDER = {BREAKING: 0, WARNING: 1, INFO: 2}


def diff(baseline: dict, current: dict, endpoint: str = "") -> list[Finding]:
    """Compare a recorded contract against a freshly inferred one."""
    if not baseline:
        return []  # nothing recorded, so nothing can have drifted
    findings: list[Finding] = []
    _diff_node(baseline, current or {}, endpoint, "", findings)
    return sorted(findings, key=lambda f: (_ORDER[f.severity], f.field, f.kind))


def _diff_node(base: dict, cur: dict, endpoint: str, path: str, out: list) -> None:
    base_type, cur_type = base.get("type"), cur.get("type")

    # A container swapping shape (object <-> array) invalidates everything below
    # it, so report that and stop rather than emitting noise for every field.
    if _is_container_change(base_type, cur_type):
        _add(out, endpoint, BREAKING, "type_changed", path,
             f"type changed from {_render(base_type)} to {_render(cur_type)}")
        return

    if base_type == "object":
        _diff_object(base, cur, endpoint, path, out)
    elif base_type == "array":
        if base.get("items") and cur.get("items"):
            _diff_node(base["items"], cur["items"], endpoint, _join(path, "[]"), out)
    else:
        _diff_leaf(base, cur, endpoint, path, out)


def _diff_object(base: dict, cur: dict, endpoint: str, path: str, out: list) -> None:
    base_props = base.get("properties") or {}
    cur_props = cur.get("properties") or {}
    base_required = set(base.get("required") or [])
    cur_required = set(cur.get("required") or [])

    for name in sorted(set(base_props) - set(cur_props)):
        severity = BREAKING if name in base_required else INFO
        detail = (
            "was required in baseline, absent in current response"
            if name in base_required
            else "optional field no longer returned"
        )
        _add(out, endpoint, severity, "field_removed", _join(path, name), detail)

    for name in sorted(set(cur_props) - set(base_props)):
        _add(out, endpoint, INFO, "field_added", _join(path, name),
             "new optional field; consider adding it to the baseline")

    for name in sorted(set(base_props) & set(cur_props)):
        field = _join(path, name)
        if name in base_required and name not in cur_required:
            _add(out, endpoint, BREAKING, "field_no_longer_required", field,
                 "was required in baseline, now missing from some responses")
        _diff_node(base_props[name], cur_props[name], endpoint, field, out)


def _diff_leaf(base: dict, cur: dict, endpoint: str, path: str, out: list) -> None:
    base_types, cur_types = _types(base), _types(cur)
    if base_types != cur_types:
        if base_types < cur_types:
            _add(out, endpoint, WARNING, "type_widened", path,
                 f"now also returns {_render(sorted(cur_types - base_types))}")
        else:
            _add(out, endpoint, BREAKING, "type_changed", path,
                 f"type changed from {_render(base.get('type'))} to {_render(cur.get('type'))}")

    base_enum, cur_enum = base.get("enum"), cur.get("enum")
    if base_enum is not None and cur_enum is not None:
        added = sorted(set(cur_enum) - set(base_enum))
        removed = sorted(set(base_enum) - set(cur_enum))
        if added:
            _add(out, endpoint, WARNING, "enum_added", path,
                 f"new value(s) {_render(added)} not in baseline enum")
        if removed:
            _add(out, endpoint, BREAKING, "enum_removed", path,
                 f"value(s) {_render(removed)} no longer observed; consumers may still send them")


def _is_container_change(base_type, cur_type) -> bool:
    """True when one side is an object/array and the other is something else.

    A type may arrive as a list (a field observed with more than one type), so
    both sides are normalised to sets before comparing.
    """
    containers = {"object", "array"}
    base = set(base_type) if isinstance(base_type, list) else {base_type}
    cur = set(cur_type) if isinstance(cur_type, list) else {cur_type}
    return bool((base | cur) & containers) and base != cur


def _types(node: dict) -> set:
    declared = node.get("type")
    if declared is None:
        return set()
    return set(declared) if isinstance(declared, list) else {declared}


def _add(out: list, endpoint: str, severity: str, kind: str, field: str, detail: str) -> None:
    out.append(Finding(endpoint=endpoint, severity=severity, kind=kind, field=field, detail=detail))


def _render(value) -> str:
    if isinstance(value, (list, set, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _join(path: str, key: str) -> str:
    if key == "[]":
        return f"{path}[]" if path else "[]"
    return f"{path}.{key}" if path else key
