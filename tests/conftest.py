import json
from pathlib import Path

import cv2
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Every test gets its own empty user-data folder."""
    monkeypatch.setenv("ACV_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def fx():
    """Screens rendered from tools/demo_list_app.py plus the rectangles of interest."""
    meta = json.loads((FIXTURES / "meta.json").read_text())
    shots = {p.stem.removeprefix("screen_"): cv2.imread(str(p)) for p in FIXTURES.glob("screen_*.png")}
    return shots, meta
