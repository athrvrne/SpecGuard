"""The one non-deterministic corner of SpecGuard.

Everything here is optional. If no provider is configured — or the one that is
fails — the deterministic matrix still produces a full suite, and the Guard half
never touches this package at all.
"""

from .provider import LLMProvider

PROVIDERS = ("claude", "ollama")


def get_provider(name: str | None, model: str | None = None) -> LLMProvider | None:
    """Build a provider by name. ``None`` means run the deterministic floor only."""
    if name is None or name.lower() in ("", "none", "off"):
        return None

    key = name.lower()
    if key == "claude":
        from .claude import ClaudeProvider

        return ClaudeProvider(model=model) if model else ClaudeProvider()
    if key == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider(model=model) if model else OllamaProvider()

    raise ValueError(f"unknown provider {name!r}; expected one of {', '.join(PROVIDERS)} or none")


__all__ = ["LLMProvider", "PROVIDERS", "get_provider"]
