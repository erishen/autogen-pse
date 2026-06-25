import pytest


@pytest.fixture
def mock_model_client():
    from unittest.mock import MagicMock

    return MagicMock()
