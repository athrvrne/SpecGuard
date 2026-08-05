"""Local (Ollama) implementation of ``LLMProvider``.

The offline path: no API key, no per-call cost, and nothing about the spec
leaves the machine. Same interface as the Claude provider, so the case designer
cannot tell them apart.
"""

DEFAULT_MODEL = "qwen2.5-coder"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT = 120  # local models on CPU are slow, not broken


class OllamaProvider:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        timeout: int = DEFAULT_TIMEOUT,
        post=None,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._post = post

    def complete(self, system: str, user: str, max_tokens: int = 16000) -> str:
        post = self._post
        if post is None:
            import requests

            post = requests.post

        response = post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        # A local model that failed to load returns an error object rather than
        # a message; treat it as "no suggestions" so generation still succeeds.
        if not isinstance(payload, dict):
            return ""
        message = payload.get("message")
        if not isinstance(message, dict):
            return ""
        return message.get("content") or ""
