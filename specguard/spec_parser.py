"""OpenAPI 3.x document -> ``EndpointModel`` list.

Fully deterministic: no LLM, no network. Given the same spec file this always
produces the same models, which is what makes the rest of the pipeline testable.
"""

from pathlib import Path

import yaml

from .models import EndpointModel

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def parse_spec(path: str | Path) -> list[EndpointModel]:
    """Parse an OpenAPI 3.x file into one ``EndpointModel`` per operation."""
    with open(path) as fh:
        spec = yaml.safe_load(fh)

    endpoints = []
    for route, path_item in (spec.get("paths") or {}).items():
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if operation is None:
                continue
            endpoints.append(_build_model(route, method, operation, path_item, spec))
    return endpoints


def _build_model(
    route: str, method: str, operation: dict, path_item: dict, spec: dict
) -> EndpointModel:
    # Parameters may be declared on the path item (shared by every operation) or
    # on the operation itself; the operation's win on a name/location clash.
    params = _merge_params(path_item.get("parameters"), operation.get("parameters"))
    success_status = _success_status(operation)
    request_schema = _request_schema(operation, spec)
    return EndpointModel(
        method=method.upper(),
        path=route,
        operation_id=operation.get("operationId", ""),
        path_params=[_param(p) for p in params if p.get("in") == "path"],
        query_params=[_param(p) for p in params if p.get("in") == "query"],
        request_schema=request_schema,
        response_schema=_response_schema(operation, success_status, spec),
        success_status=success_status,
        declared_statuses=_declared_statuses(operation),
        requires_auth=_requires_auth(operation, spec),
        description=operation.get("summary") or operation.get("description") or "",
        field_descriptions=_field_descriptions(request_schema),
    )


def _field_descriptions(schema: dict | None, prefix: str = "") -> dict[str, str]:
    """Every described property in a request body, keyed by dotted path."""
    described: dict[str, str] = {}
    for name, prop in ((schema or {}).get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        dotted = f"{prefix}{name}"
        if prop.get("description"):
            described[dotted] = prop["description"]
        described |= _field_descriptions(prop, prefix=f"{dotted}.")
    return described


def _requires_auth(operation: dict, spec: dict) -> bool:
    """An operation's ``security`` overrides the document's, including ``[]``."""
    security = operation.get("security", spec.get("security"))
    return bool(security)


def _merge_params(shared: list | None, own: list | None) -> list[dict]:
    merged = {(p.get("name"), p.get("in")): p for p in shared or {}}
    merged.update({(p.get("name"), p.get("in")): p for p in own or {}})
    return list(merged.values())


def _param(param: dict) -> dict:
    return {
        "name": param.get("name", ""),
        "required": bool(param.get("required", False)),
        "schema": param.get("schema", {}),
        "description": param.get("description", ""),
    }


def _declared_statuses(operation: dict) -> list[int]:
    """Documented response codes, ascending. ``default`` is not a status."""
    return sorted(
        int(code)
        for code in (operation.get("responses") or {})
        if str(code).isdigit()
    )


def _success_status(operation: dict) -> int:
    """The lowest declared 2xx response code, defaulting to 200."""
    codes = [
        int(code)
        for code in (operation.get("responses") or {})
        if str(code).isdigit() and 200 <= int(code) < 300
    ]
    return min(codes) if codes else 200


def _request_schema(operation: dict, spec: dict) -> dict | None:
    body = operation.get("requestBody") or {}
    return _json_schema(body.get("content"), spec)


def _response_schema(operation: dict, success_status: int, spec: dict) -> dict | None:
    response = (operation.get("responses") or {}).get(str(success_status)) or {}
    return _json_schema(response.get("content"), spec)


def _json_schema(content: dict | None, spec: dict) -> dict | None:
    """Pull the JSON media type's schema out of an OpenAPI ``content`` block."""
    for media_type, media in (content or {}).items():
        if media_type == "application/json" or media_type.endswith("+json"):
            schema = media.get("schema")
            return _resolve(schema, spec) if schema is not None else None
    return None


def _resolve(node, spec: dict, seen: frozenset[str] = frozenset()):
    """Inline every local ``$ref`` so downstream modules never touch the spec.

    ``seen`` carries the refs already expanded on this branch: a self-referential
    schema (a tree node with a ``parent``) would otherwise recurse forever, so
    the second sighting of a ref is left unexpanded.
    """
    if isinstance(node, list):
        return [_resolve(item, spec, seen) for item in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return dict(node)
        target = _lookup(ref, spec)
        if target is None:
            return dict(node)
        return _resolve(target, spec, seen | {ref})

    return {key: _resolve(value, spec, seen) for key, value in node.items()}


def _lookup(ref: str, spec: dict) -> dict | None:
    """Follow a local JSON pointer such as ``#/components/schemas/Pet``."""
    if not ref.startswith("#/"):
        return None  # remote refs are out of scope for v1
    node = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None
