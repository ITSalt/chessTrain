import json
from pathlib import Path
import pytest


@pytest.fixture
def inputs():
    root = Path(__file__).parents[1] / 'fixtures'
    return {name: json.loads((root / f'{name}.json').read_text())
            for name in ('manifest', 'config', 'responses', 'engine', 'asr')}
