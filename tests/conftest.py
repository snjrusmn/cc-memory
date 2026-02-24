"""Shared test fixtures for CC-Memory."""

import pytest

from cc_memory.storage import Storage


@pytest.fixture
def storage():
    """In-memory storage for tests."""
    s = Storage(":memory:")
    s.init_db()
    yield s
    s.close()
