import pytest

from acv.desktop import parse_keys


def test_parse_keys():
    assert parse_keys("Ctrl+Shift+S") == ["ctrl", "shift", "s"]
    assert parse_keys("Escape") == ["esc"]
    assert parse_keys("f5") == ["f5"]


@pytest.mark.parametrize("bad", ["", "ctrl+", "hyper+x", "f13"])
def test_parse_keys_rejects_unknown(bad):
    with pytest.raises(ValueError):
        parse_keys(bad)
