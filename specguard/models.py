"""Core data models shared by both SpecGuard pipelines.

Everything in this module is plain data: no I/O, no model calls. The Generate
pipeline produces ``EndpointModel`` then ``TestCase``; the Guard pipeline
produces ``Finding``.
"""

from dataclasses import dataclass, field


@dataclass
class EndpointModel:
    """One operation from an OpenAPI document, flattened for downstream use."""

    method: str  # GET, POST, ...
    path: str  # /pets/{petId}
    operation_id: str
    path_params: list[dict] = field(default_factory=list)
    query_params: list[dict] = field(default_factory=list)
    request_schema: dict | None = None  # JSON Schema of the request body
    response_schema: dict | None = None  # JSON Schema of the success body
    success_status: int = 200  # 200 / 201 / 204
    # Every numeric status the operation documents, ascending. Lets the case
    # designer expect the API's own error codes instead of assuming 422/401.
    declared_statuses: list[int] = field(default_factory=list)
    requires_auth: bool = False
    description: str = ""
    # Natural-language notes per request-body field, keyed by dotted path. These
    # are the only input the LLM gets in the Generate half: a rule like "must be
    # a future date" lives here because no JSON Schema keyword can express it.
    field_descriptions: dict[str, str] = field(default_factory=dict)


@dataclass
class TestCase:
    """One case the renderer turns into a pytest function."""

    # The name collides with pytest's collection heuristic: anything called
    # Test* in an imported module gets picked up as a test class. This opts out,
    # for SpecGuard's own suite and for anyone importing the model.
    __test__ = False

    name: str
    kind: str  # happy | validation | boundary | auth | llm_extra
    method: str
    path: str
    expected_status: int
    body: dict | None = None
    query: dict = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    assertions: list = field(default_factory=list)
    # False only for the auth-boundary case, which must arrive with no
    # credentials however the suite is otherwise configured.
    send_auth: bool = True
    # Set when a human has to look at this case before trusting it: an LLM
    # proposed it, or SpecGuard had to invent data the spec didn't supply.
    needs_review: bool = False
    # Why. Rendered as a REVIEW comment above the test so it can be confirmed
    # or deleted in seconds; empty for cases that stand on their own.
    reason: str = ""


@dataclass
class Finding:
    """One drift observation. Serialises directly into ``drift_report.json``."""

    endpoint: str  # "GET /v1/orders/{id}"
    severity: str  # breaking | warning | info
    kind: str  # field_removed | field_added | type_changed | enum_added | ...
    # Dotted path to the drifted field, e.g. "customer.address.postcode". Nested
    # responses are the norm, so this is a path from the start: making it a bare
    # name now would mean migrating every recorded baseline later.
    field: str
    detail: str = ""

