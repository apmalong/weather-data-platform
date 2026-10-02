from pathlib import Path

import pytest

from wx import ops
from wx.noaa import load

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def readme() -> str:
    return (FIXTURES / "readme.txt").read_text(encoding="utf-8")


@pytest.fixture
def conn():
    """An in-memory warehouse with the ops and raw schemas."""
    connection = ops.connect(":memory:")
    load.ensure_schema(connection)
    yield connection
    connection.close()
