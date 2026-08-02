"""``EndpointModel`` -> ``TestCase`` list.

The deterministic matrix here is the floor: it runs with no model configured and
always produces the same cases for the same spec. An ``LLMProvider`` only ever
*adds* to it.
"""

from .models import EndpointModel, TestCase

# Values used when the spec gives us nothing better to go on.
_BY_TYPE = {
    "string": "string",
    "integer": 1,
    "number": 1.0,
    "boolean": True,
    "array": [],
    "object": {},
}


def design_cases(ep: EndpointModel, llm=None) -> list[TestCase]:
    """Every test case for one endpoint. ``llm`` adds to the floor, never replaces it."""
    return _deterministic_matrix(ep)


def _deterministic_matrix(ep: EndpointModel) -> list[TestCase]:
    cases = [_happy(ep), *_validation_cases(ep), *_boundary_cases(ep)]
    if ep.requires_auth:
        cases.append(_auth_case(ep))
    return cases


# --- happy path -------------------------------------------------------------


def _happy(ep: EndpointModel) -> TestCase:
    path, unresolved = _concrete_path(ep)
    return TestCase(
        name=f"test_{_slug(ep)}_happy_path",
        kind="happy",
        method=ep.method,
        path=path,
        expected_status=ep.success_status,
        body=_example_body(ep.request_schema),
        query=_required_query(ep),
        needs_review=bool(unresolved),
        reason=_unresolved_reason(unresolved),
    )


def _unresolved_reason(unresolved: list[str]) -> str:
    if not unresolved:
        return ""
    names = ", ".join(unresolved)
    return (
        f"path parameter(s) {names} were invented — the spec gives no example, "
        f"so this will 404 until a real value is supplied"
    )


# --- validation -------------------------------------------------------------

# Codes an API plausibly uses to reject a malformed body, in preference order.
_VALIDATION_CODES = (422, 400)
_WRONG_TYPE = {
    "string": 12345,
    "integer": "not-a-number",
    "number": "not-a-number",
    "boolean": "not-a-boolean",
    "array": "not-an-array",
    "object": "not-an-object",
}


def _validation_cases(ep: EndpointModel) -> list[TestCase]:
    """One case per required field missing, one per field with the wrong type."""
    body = _example_body(ep.request_schema)
    if body is None:
        return []

    required = (ep.request_schema or {}).get("required") or []
    properties = (ep.request_schema or {}).get("properties") or {}
    expected = _validation_status(ep)
    path, _ = _concrete_path(ep)
    cases = []

    for name in required:
        if name not in body:
            continue
        cases.append(
            _validation_case(ep, path, expected, f"{name}_missing", _without(body, name))
        )

    for name, prop in properties.items():
        wrong = _WRONG_TYPE.get((prop or {}).get("type"))
        if wrong is None:
            continue
        cases.append(
            _validation_case(
                ep, path, expected, f"{name}_wrong_type", {**body, name: wrong}
            )
        )

    return cases


def _validation_case(
    ep: EndpointModel, path: str, expected: int, suffix: str, body: dict
) -> TestCase:
    return TestCase(
        name=f"test_{_slug(ep)}_{suffix}",
        kind="validation",
        method=ep.method,
        path=path,
        expected_status=expected,
        body=body,
        query=_required_query(ep),
    )


def _validation_status(ep: EndpointModel) -> int:
    for code in _VALIDATION_CODES:
        if code in ep.declared_statuses:
            return code
    return _VALIDATION_CODES[0]


def _without(body: dict, name: str) -> dict:
    return {k: v for k, v in body.items() if k != name}


# --- boundary ---------------------------------------------------------------

# (suffix, keyword, offset from the declared bound, is the value still legal?)
_LENGTH_PROBES = (
    ("min_length", "minLength", 0, True),
    ("max_length", "maxLength", 0, True),
    ("under_min_length", "minLength", -1, False),
    ("over_max_length", "maxLength", +1, False),
)
_NUMERIC_PROBES = (
    ("minimum", "minimum", 0, True),
    ("maximum", "maximum", 0, True),
    ("under_minimum", "minimum", -1, False),
    ("over_maximum", "maximum", +1, False),
)


def _boundary_cases(ep: EndpointModel) -> list[TestCase]:
    """Each declared bound probed at the edge and one step past it."""
    body = _example_body(ep.request_schema)
    path, _ = _concrete_path(ep)
    query = _required_query(ep)
    reject = _validation_status(ep)
    cases = []

    properties = (ep.request_schema or {}).get("properties") or {}
    for name, prop in properties.items():
        for suffix, value, legal in _probe_values(prop):
            cases.append(
                TestCase(
                    name=f"test_{_slug(ep)}_{name}_{suffix}",
                    kind="boundary",
                    method=ep.method,
                    path=path,
                    expected_status=ep.success_status if legal else reject,
                    body={**(body or {}), name: value},
                    query=query,
                )
            )

    for param in ep.query_params:
        name = param["name"]
        for suffix, value, legal in _probe_values(param.get("schema") or {}):
            cases.append(
                TestCase(
                    name=f"test_{_slug(ep)}_{name}_{suffix}",
                    kind="boundary",
                    method=ep.method,
                    path=path,
                    expected_status=ep.success_status if legal else reject,
                    body=body,
                    query={**query, name: value},
                )
            )

    return cases


def _probe_values(schema: dict) -> list[tuple[str, object, bool]]:
    """Edge values for one field, empty when the field declares no bounds."""
    if not isinstance(schema, dict):
        return []
    numeric = schema.get("type") in ("integer", "number")
    probes = _NUMERIC_PROBES if numeric else _LENGTH_PROBES

    out = []
    for suffix, keyword, offset, legal in probes:
        bound = schema.get(keyword)
        if bound is None:
            continue
        target = bound + offset
        if numeric:
            value = int(target) if schema.get("type") == "integer" else float(target)
        else:
            if target < 0:
                continue  # no string is shorter than empty
            value = "a" * int(target)
        out.append((suffix, value, legal))
    return out


# --- auth -------------------------------------------------------------------


def _auth_case(ep: EndpointModel) -> TestCase:
    """The same request with no credentials attached."""
    path, _ = _concrete_path(ep)
    expected = next(
        (code for code in (401, 403) if code in ep.declared_statuses),
        401,
    )
    return TestCase(
        name=f"test_{_slug(ep)}_requires_auth",
        kind="auth",
        method=ep.method,
        path=path,
        expected_status=expected,
        body=_example_body(ep.request_schema),
        query=_required_query(ep),
        send_auth=False,
    )


# --- value synthesis --------------------------------------------------------


def _example_value(schema: dict | None):
    """A plausible value for one field, preferring anything the spec states."""
    if not isinstance(schema, dict):
        return None
    for key in ("example", "default"):
        if key in schema:
            return schema[key]
    if schema.get("enum"):
        return schema["enum"][0]

    type_ = schema.get("type")
    if type_ == "object":
        return _example_body(schema) or {}
    if type_ == "array":
        item = _example_value(schema.get("items"))
        return [item] if item is not None else []
    if type_ in ("integer", "number"):
        # Respect a declared range so the happy path isn't rejected by the API.
        return _in_range(schema, type_)
    if type_ == "string":
        return _string_in_range(schema)
    return _BY_TYPE.get(type_)


def _in_range(schema: dict, type_: str):
    low, high = schema.get("minimum"), schema.get("maximum")
    value = low if low is not None else (high if high is not None else 1)
    return int(value) if type_ == "integer" else float(value)


def _string_in_range(schema: dict) -> str:
    value = "string"
    minimum, maximum = schema.get("minLength"), schema.get("maxLength")
    if minimum is not None and len(value) < minimum:
        value = "a" * minimum
    if maximum is not None and len(value) > maximum:
        value = value[:maximum]
    return value


def _example_body(schema: dict | None) -> dict | None:
    """A request body satisfying ``schema``, or ``None`` if there is no body."""
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    if not properties:
        return None
    return {name: _example_value(prop) for name, prop in properties.items()}


# --- request shaping --------------------------------------------------------


def _concrete_path(ep: EndpointModel) -> tuple[str, list[str]]:
    """Substitute path params, reporting any whose value we had to invent."""
    path, unresolved = ep.path, []
    for param in ep.path_params:
        schema = param.get("schema") or {}
        stated = any(k in schema for k in ("example", "default", "enum"))
        value = _example_value(schema)
        if value is None:
            value = "1"
        if not stated:
            unresolved.append(param["name"])
        path = path.replace("{" + param["name"] + "}", str(value))
    return path, unresolved


def _required_query(ep: EndpointModel) -> dict:
    return {
        param["name"]: _example_value(param.get("schema"))
        for param in ep.query_params
        if param.get("required")
    }


def _slug(ep: EndpointModel) -> str:
    if ep.operation_id:
        return _snake(ep.operation_id)
    trail = "_".join(p.strip("{}") for p in ep.path.strip("/").split("/") if p)
    return f"{ep.method.lower()}_{trail or 'root'}"


def _snake(name: str) -> str:
    out = []
    for index, char in enumerate(name):
        if char.isupper() and index and not name[index - 1].isupper():
            out.append("_")
        out.append(char.lower())
    return "".join(out)
