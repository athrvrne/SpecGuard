from specguard.llm.provider import LLMProvider


class StubProvider:
    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        return "[]"


class NotAProvider:
    def generate(self, prompt: str) -> str:
        return "[]"


def test_anything_with_a_complete_method_satisfies_the_protocol():
    assert isinstance(StubProvider(), LLMProvider)


def test_an_object_without_complete_does_not_satisfy_the_protocol():
    assert not isinstance(NotAProvider(), LLMProvider)
