import numpy as np

from acv import vision
from acv.model import Rect


def rect(values):
    return Rect(*values)


def test_finds_anchor_and_row_on_other_screens(fx):
    shots, meta = fx
    anchor = vision.crop(shots["list_full"], rect(meta["anchor"]))
    a = rect(meta["anchor"])
    for name in ("list_full", "list_next", "list_empty"):
        status, m = vision.locate(shots[name], anchor, 0.85)
        assert status == vision.FOUND, name
        assert (m.x, m.y) == (a.x, a.y)


def test_anchor_missing():
    shots_blank = np.full((300, 300, 3), 128, np.uint8)
    tpl = np.random.default_rng(0).integers(0, 255, (20, 40, 3), dtype=np.uint8)
    assert vision.locate(shots_blank, tpl, 0.85)[0] == vision.MISSING


def test_ambiguous_when_repeated():
    tpl = np.random.default_rng(0).integers(0, 255, (20, 40, 3), dtype=np.uint8)
    screen = np.full((200, 300, 3), 128, np.uint8)
    screen[10:30, 10:50] = tpl
    screen[100:120, 200:240] = tpl
    assert vision.locate(screen, tpl, 0.85)[0] == vision.AMBIGUOUS


def test_row_full_vs_empty(fx):
    shots, meta = fx
    a, r = rect(meta["anchor"]), rect(meta["first_row"])
    offset = Rect(r.x - a.x, r.y - a.y, r.w, r.h)
    full_row = vision.crop(shots["list_full"], vision.row_rect(vision.Match(a.x, a.y, a.w, a.h, 1), offset))
    empty_row = vision.crop(shots["list_empty"], vision.row_rect(vision.Match(a.x, a.y, a.w, a.h, 1), offset))
    next_row = vision.crop(shots["list_next"], vision.row_rect(vision.Match(a.x, a.y, a.w, a.h, 1), offset))
    filled = vision.row_score(full_row)
    assert vision.is_row_filled(full_row, filled)
    assert vision.is_row_filled(next_row, filled)
    assert not vision.is_row_filled(empty_row, filled)
    assert vision.rows_differ(full_row, next_row)
    assert not vision.rows_differ(full_row, full_row.copy())


def test_empty_sample_with_lines_counts_as_empty():
    row = np.full((24, 300, 3), 255, np.uint8)
    row[::6] = 0  # grid lines: looks "busy" but is an empty row
    assert vision.is_row_filled(row, 0.1)
    assert not vision.is_row_filled(row, 0.1, empty_sample=row.copy())


def test_crop_unique_grows_until_unique(fx):
    shots, meta = fx
    screen = shots["review_dialog"]
    b = rect(meta["approve_button"])
    cx, cy = b.x + b.w // 2, b.y + b.h // 2
    tpl, r, unique = vision.crop_unique(screen, cx, cy, 0.85)
    assert unique
    assert r.x <= cx < r.x + r.w and r.y <= cy < r.y + r.h
    assert vision.locate(screen, tpl, 0.85)[0] == vision.FOUND


def test_crop_unique_reports_repeated_pattern():
    tile = np.random.default_rng(0).integers(0, 255, (30, 30, 3), dtype=np.uint8)
    screen = np.tile(tile, (10, 10, 1))  # same pattern everywhere
    _, _, unique = vision.crop_unique(screen, 150, 150, 0.85, largest=(60, 60))
    assert not unique


def test_crop_outside_returns_none():
    assert vision.crop(np.zeros((10, 10, 3), np.uint8), Rect(5, 5, 10, 10)) is None
