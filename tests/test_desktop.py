import sys

import pytest

from acv import desktop
from acv.desktop import parse_keys


def test_parse_keys():
    assert parse_keys("Ctrl+Shift+S") == ["ctrl", "shift", "s"]
    assert parse_keys("Escape") == ["esc"]
    assert parse_keys("f5") == ["f5"]


@pytest.mark.parametrize("bad", ["", "ctrl+", "hyper+x", "f13"])
def test_parse_keys_rejects_unknown(bad):
    with pytest.raises(ValueError):
        parse_keys(bad)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 calls")
def test_win32_calls_work():
    desktop.set_dpi_awareness()
    monitors = desktop.list_monitors()
    assert monitors and all(m.scale > 0 for m in monitors)
    frame = desktop.MssScreen(monitors[0]).grab()
    assert frame.shape == (monitors[0].height, monitors[0].width, 3)
    assert isinstance(desktop.root_window_at(monitors[0].left + 5, monitors[0].top + 5), int)
