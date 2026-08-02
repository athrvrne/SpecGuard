"""The seam that makes the model pluggable.

Every non-deterministic thing SpecGuard does goes through this one method, which
is what keeps the rest of the codebase reproducible. Implementations live beside
this module (``claude.py``, ``ollama.py``) and are never imported by the Guard
pipeline.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """A single text-in, text-out call. No streaming, no tools, no state."""

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str: ...
