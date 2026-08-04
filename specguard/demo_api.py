"""A tiny API that honours ``examples/petstore.yaml``, with drift on demand.

Two jobs. It proves a generated suite genuinely goes green against a conforming
API — the only way to know the Generate half works end to end. And it can be
told to break its own contract, which is what makes the Guard demo runnable
offline in four commands: generate, baseline, break, guard.

Stdlib only, so it ships in the wheel and ``pip install specguard`` is enough.
Not a mock server for your own spec — point Prism at that.
"""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PET = {"id": "p_1", "name": "Rex", "tag": "good-boy", "status": "available"}
STATUSES = {"available", "pending", "sold"}
_PET_PATH = re.compile(r"^/pets/[^/]+$")

# Whether the API still validates its input. Read at request time so it can be
# changed while the server is running.
STRICT = True


def apply_drift(rename: str | None = None, add: str | None = None, lax: bool = False) -> None:
    """Break the API's contract in a specific, reproducible way.

    ``rename`` takes ``OLD:NEW`` and is the breaking case — a required field
    disappears. ``add`` introduces a new optional field, which is only ever
    informational. ``lax`` stops the API rejecting invalid payloads, which no
    schema diff can catch but the generated validation tests will.
    """
    global PET, STRICT

    pet = dict(PET)
    if rename:
        old, sep, new = rename.partition(":")
        if not sep or not old or not new:
            raise ValueError(f"--rename expects OLD:NEW, got {rename!r}")
        if old not in pet:
            raise ValueError(f"{old!r} is not a field of the demo pet: {sorted(pet)}")
        pet = {new if key == old else key: value for key, value in pet.items()}
    if add:
        pet[add] = "2026-01-01T00:00:00Z"

    PET = pet
    STRICT = not lax


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the test output pristine
        pass

    # --- plumbing ---------------------------------------------------------

    def _send(self, status, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _authed(self):
        return self.headers.get("Authorization", "").startswith("Bearer ")

    def _query(self):
        _, _, raw = self.path.partition("?")
        out = {}
        for pair in raw.split("&"):
            if "=" in pair:
                key, _, value = pair.partition("=")
                out[key] = value
        return out

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    @property
    def _route(self):
        return self.path.split("?", 1)[0]

    # --- routes -----------------------------------------------------------

    def do_GET(self):
        if self._route == "/pets":
            query = self._query()
            if query.get("status") not in STATUSES:
                return self._send(422, {"code": 422, "message": "bad status"})
            if "limit" in query:
                try:
                    limit = int(query["limit"])
                except ValueError:
                    return self._send(422, {"code": 422, "message": "bad limit"})
                if not 1 <= limit <= 100:
                    return self._send(422, {"code": 422, "message": "limit out of range"})
            return self._send(200, [PET])

        if _PET_PATH.match(self._route):
            if not self._authed():
                return self._send(401, {"code": 401, "message": "unauthorized"})
            return self._send(200, PET)

        self._send(404, {"code": 404, "message": "not found"})

    def do_POST(self):
        if self._route != "/pets":
            return self._send(404, {"code": 404, "message": "not found"})
        if not self._authed():
            return self._send(401, {"code": 401, "message": "unauthorized"})

        body = self._body()
        if not STRICT:
            return self._send(201, PET)
        if not isinstance(body, dict):
            return self._send(422, {"code": 422, "message": "body must be an object"})

        name, status, tag = body.get("name"), body.get("status"), body.get("tag")
        if not isinstance(name, str) or not 1 <= len(name) <= 40:
            return self._send(422, {"code": 422, "message": "bad name"})
        if status not in STATUSES:
            return self._send(422, {"code": 422, "message": "bad status"})
        if tag is not None and not isinstance(tag, str):
            return self._send(422, {"code": 422, "message": "bad tag"})

        return self._send(201, {**PET, "name": name, "status": status})

    def do_DELETE(self):
        if not _PET_PATH.match(self._route):
            return self._send(404, {"code": 404, "message": "not found"})
        if not self._authed():
            return self._send(401, {"code": 401, "message": "unauthorized"})
        self._send(204)


class DemoServer:
    """The demo API, on a background thread. Yields the base URL it bound to.

    Port 0 asks the OS for a free port, so tests never collide.
    """

    def __init__(self, port: int = 0, host: str = "127.0.0.1"):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def start(self) -> str:
        self.server = HTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.url

    def stop(self) -> None:
        if self.server is None:
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.server = None

    def __enter__(self) -> str:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
