"""Shared fixtures."""

import pytest

from care_agent.ehr.db import connect, init_db
from ehr_data import seed_reference_data


@pytest.fixture
def conn(tmp_path):
    """A fresh, initialised EHR database file in pytest's temp dir, with reference data."""
    connection = connect(tmp_path / "ehr.sqlite3")
    init_db(connection)
    seed_reference_data(connection)
    yield connection
    connection.close()
