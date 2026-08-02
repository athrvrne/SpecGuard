"""Capture real responses while a test suite runs.

Baselining needs real request data — a real order id, a real auth token. A spec
can't supply those, and inventing them means recording a 404 body as your
contract and never noticing.

So SpecGuard doesn't invent them: it watches a suite that already works. The
suite has real ids in it because a human made it pass. Recording hooks
``requests`` rather than anything SpecGuard generated, so it works just as well
on a hand-written suite.
"""

from urllib.parse import urlsplit

import requests

# Bodies are only recorded for successful responses. A 4xx body is a different
# shape (an error envelope) and pooling the two would infer a schema matching
# neither.
SUCCESS = range(200, 300)


def endpoint_key(method: str, url: str, routes: list[str]) -> str:
    """Fold a concrete URL back onto the templated route it came from.

    ``GET /pets/p_1`` becomes ``GET /pets/{petId}`` so that every call to an
    endpoint accumulates into one baseline entry instead of one per resource id.
    """
    path = urlsplit(url).path or "/"
    return f"{method.upper()} {_match_route(path, routes)}"


def _match_route(path: str, routes: list[str]) -> str:
    segments = _segments(path)
    for route in routes:
        template = _segments(route)
        if len(template) != len(segments):
            continue
        if all(
            expected.startswith("{") or expected == actual
            for expected, actual in zip(template, segments)
        ):
            return route
    return path


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s]


class Recorder:
    """Context manager that captures every ``requests`` call made inside it.

    Instruments ``requests.Session.send``, which every requests API funnels
    through, so it sees calls made via ``requests.get`` and via a Session alike.
    """

    def __init__(self, routes: list[str] | None = None):
        self.routes = list(routes or [])
        self.captured: dict[str, dict] = {}
        self._original = None

    def __enter__(self) -> "Recorder":
        self._original = requests.Session.send
        recorder = self

        def send(session, request, **kwargs):
            response = recorder._original(session, request, **kwargs)
            recorder._capture(request, response)
            return response

        requests.Session.send = send
        return self

    def __exit__(self, *exc) -> None:
        if self._original is not None:
            requests.Session.send = self._original
            self._original = None

    def _capture(self, request, response) -> None:
        key = endpoint_key(request.method, request.url, self.routes)
        entry = self.captured.setdefault(key, {"statuses": [], "bodies": []})
        entry["statuses"].append(response.status_code)

        if response.status_code not in SUCCESS:
            return
        body = _json_body(response)
        if body is not None:
            entry["bodies"].append(body)


def _json_body(response):
    """The decoded JSON body, or ``None`` for empty and non-JSON responses."""
    if not response.content:
        return None
    content_type = response.headers.get("Content-Type", "")
    if "json" not in content_type:
        return None
    try:
        return response.json()
    except ValueError:
        return None
