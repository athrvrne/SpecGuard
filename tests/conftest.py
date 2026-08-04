from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="session")
def petstore_path() -> Path:
    return EXAMPLES / "petstore.yaml"


@pytest.fixture
def restore_demo_api():
    """Undo any drift staged on the demo API's module-level state."""
    from specguard import demo_api

    before = (demo_api.PET, demo_api.STRICT)
    yield
    demo_api.PET, demo_api.STRICT = before
