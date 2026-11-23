"""Local computer vision: template matching, unique crops and empty-row detection."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .model import Rect

FOUND, MISSING, AMBIGUOUS = "found", "missing", "ambiguous"
MIN_ROW_SCORE = 0.02  # below this a row is plain background whatever was recorded
EMPTY_RATIO = 0.3  # a row scoring under 30 % of the recorded filled row is empty
UNIQUE_MARGIN = 0.05  # crops must be unique even at (confidence - margin)


@dataclass
class Match:
    x: int
    y: int
    w: int
    h: int
    score: float


def gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def has_detail(img: np.ndarray) -> bool:
    """A flat patch matches everywhere, so it can never be a reliable target."""
    return img.size > 0 and float(gray(img).std()) >= 4.0


def find_all(screen: np.ndarray, template: np.ndarray, confidence: float, max_results: int = 2) -> list[Match]:
    s, t = gray(screen), gray(template)
    th, tw = t.shape
    if th > s.shape[0] or tw > s.shape[1] or not has_detail(t):
        return []
    res = cv2.matchTemplate(s, t, cv2.TM_CCOEFF_NORMED)
    np.nan_to_num(res, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    matches = []
    for _ in range(max_results):
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        if score < confidence:
            break
        matches.append(Match(x, y, tw, th, float(score)))
        # suppress this peak and its neighbours so the next one is a different place
        res[max(0, y - th // 2): y + th // 2 + 1, max(0, x - tw // 2): x + tw // 2 + 1] = -1
    return matches


def locate(screen: np.ndarray, template: np.ndarray, confidence: float) -> tuple[str, Match | None]:
    """Find exactly one occurrence. Several matches are reported as ambiguous, never guessed."""
    matches = find_all(screen, template, confidence, 2)
    if not matches:
        return MISSING, None
    if len(matches) > 1:
        return AMBIGUOUS, matches[0]
    return FOUND, matches[0]


def crop(img: np.ndarray, r: Rect) -> np.ndarray | None:
    """Crop a rectangle; None if it is not fully inside the image."""
    if r.w <= 0 or r.h <= 0 or r.x < 0 or r.y < 0 or r.x + r.w > img.shape[1] or r.y + r.h > img.shape[0]:
        return None
    return img[r.y:r.y + r.h, r.x:r.x + r.w].copy()


def crop_unique(screen: np.ndarray, x: int, y: int, confidence: float,
                start: tuple[int, int] = (48, 24), largest: tuple[int, int] = (480, 240)
                ) -> tuple[np.ndarray, Rect, bool]:
    """Crop around (x, y), growing until the crop appears only once on screen.

    Returns (crop, rect, unique). If it is still not unique at the largest size, unique is False.
    """
    sh, sw = screen.shape[:2]
    w, h = start
    while True:
        w, h = min(w, sw), min(h, sh)
        left = min(max(0, x - w // 2), sw - w)
        top = min(max(0, y - h // 2), sh - h)
        rect = Rect(left, top, w, h)
        tpl = crop(screen, rect)
        if has_detail(tpl) and len(find_all(screen, tpl, confidence - UNIQUE_MARGIN, 2)) == 1:
            return tpl, rect, True
        if (w, h) == (min(largest[0], sw), min(largest[1], sh)):
            return tpl, rect, False
        w, h = min(int(w * 1.5), largest[0]), min(int(h * 1.5), largest[1])


# --- first row ---

def row_score(img: np.ndarray) -> float:
    """How much 'content' a row has: edge density plus grey-level spread. Background scores ~0."""
    g = gray(img)
    edges = cv2.Canny(g, 50, 150)
    return float(edges.mean() / 255.0 + g.std() / 255.0)


def rows_differ(a: np.ndarray, b: np.ndarray) -> bool:
    """True if two row images show something different (e.g. another item). Robust to tiny noise."""
    if a.shape != b.shape:
        return True
    diff = cv2.absdiff(gray(a), gray(b))
    changed = int(np.count_nonzero(diff > 40))
    return changed >= max(15, int(0.001 * diff.size))


def is_row_filled(row: np.ndarray, filled_score: float, empty_sample: np.ndarray | None = None) -> bool:
    if empty_sample is not None and not rows_differ(row, empty_sample):
        return False
    return row_score(row) >= max(MIN_ROW_SCORE, EMPTY_RATIO * filled_score)


def row_rect(anchor: Match, offset: Rect) -> Rect:
    return Rect(anchor.x + offset.x, anchor.y + offset.y, offset.w, offset.h)
