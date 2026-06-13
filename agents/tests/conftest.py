"""Shared pytest fixtures for agent storage tests."""

import pytest
from pathlib import Path
import tempfile

from agents.storage.db import create_all_tables, get_schema_version


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    """Fresh in-memory-equivalent DB in a temp directory."""
    db = tmp_path / "test_agents.db"
    create_all_tables(db)
    return db
