"""A pytest plugin that records every response a suite receives.

Loaded explicitly with ``-p specguard.record``, never by import, so a generated
suite still depends on nothing but pytest and requests. It hooks ``requests``
rather than anything SpecGuard emitted, which is why it works just as well on a
hand-written suite.

Configured entirely through the environment, because the plugin runs in a
subprocess the CLI spawns:

``SPECGUARD_ROUTES``   JSON array of templated routes, for folding concrete
                      URLs back onto the endpoint they belong to.
``SPECGUARD_CAPTURE``  path to write the captured responses to.
"""

import json
import os

from .runner import Recorder

_recorder: Recorder | None = None


def pytest_sessionstart(session):
    global _recorder
    if not os.environ.get("SPECGUARD_CAPTURE"):
        return
    routes = json.loads(os.environ.get("SPECGUARD_ROUTES", "[]"))
    _recorder = Recorder(routes)
    _recorder.__enter__()


def pytest_sessionfinish(session, exitstatus):
    global _recorder
    if _recorder is None:
        return
    _recorder.__exit__(None, None, None)
    path = os.environ["SPECGUARD_CAPTURE"]
    with open(path, "w") as fh:
        json.dump(_recorder.captured, fh)
    _recorder = None
