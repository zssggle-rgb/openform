import json
from pathlib import Path

import pytest


EXAMPLES = Path(__file__).parents[1] / "examples"


@pytest.fixture
def words():
    return json.loads((EXAMPLES / "words" / "manifest.json").read_text())
