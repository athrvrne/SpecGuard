"""Claude implementation of ``LLMProvider``.

Only reached by ``specguard generate``. The Guard half never imports this.
"""

DEFAULT_MODEL = "claude-opus-5"

# Thinking is on by default on this model family, and max_tokens caps thinking
# *plus* response text together — a tight budget truncates the JSON mid-array
# and the whole batch is then dropped by the parser.
DEFAULT_MAX_TOKENS = 16000


class ClaudeProvider:
    """Text in, text out. No streaming, no tools, no conversation state."""

    def __init__(self, model: str = DEFAULT_MODEL, client=None):
        self.model = model
        if client is None:
            import anthropic  # imported lazily so `anthropic` stays an extra

            client = anthropic.Anthropic()  # key from the environment
        self.client = client

    def complete(self, system: str, user: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # A safety classifier can decline the request: HTTP 200, no content.
        # Indexing into content here would raise instead of degrading to the
        # deterministic matrix.
        if getattr(response, "stop_reason", None) == "refusal":
            return ""
        return "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
