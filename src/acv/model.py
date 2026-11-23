"""Flow data model and its JSON (de)serialisation."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields

SCHEMA_VERSION = 1

# Step types
CLICK_IMAGE = "click_image"
CLICK_POINT = "click_point"
KEY = "key"
TEXT = "text"
WAIT = "wait"
WAIT_IMAGE = "wait_image"
STEP_TYPES = (CLICK_IMAGE, CLICK_POINT, KEY, TEXT, WAIT, WAIT_IMAGE)
IMAGE_STEPS = (CLICK_IMAGE, WAIT_IMAGE)

STEP_TYPE_NAMES = {
    CLICK_IMAGE: "Click on image",
    CLICK_POINT: "Click at fixed position",
    KEY: "Press key",
    TEXT: "Type text",
    WAIT: "Wait",
    WAIT_IMAGE: "Wait for image",
}


@dataclass
class Rect:
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


@dataclass
class Point:
    x: int = 0
    y: int = 0


@dataclass
class MonitorInfo:
    index: int = 1  # 1-based, as shown to the user
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    scale: float = 1.0


@dataclass
class FirstRow:
    offset: Rect = field(default_factory=Rect)  # relative to the anchor's top-left corner
    filled_score: float = 0.0
    empty_sample: str | None = None  # image file of the row when the list is empty


@dataclass
class Step:
    type: str = CLICK_IMAGE
    label: str = ""
    image: str | None = None  # image file, for click_image / wait_image
    button: str = "left"  # left | right
    clicks: int = 1  # 1 = single, 2 = double
    click_offset: Point = field(default_factory=Point)  # click position inside the image
    point: Point = field(default_factory=Point)  # click_point: offset from the anchor
    confidence: float = 0.85
    timeout_s: float = 10.0
    delay_after_s: float = 0.3
    keys: str = ""  # key: e.g. "enter", "ctrl+s"
    text: str = ""  # text: what to type
    seconds: float = 1.0  # wait: how long

    def describe(self) -> str:
        base = STEP_TYPE_NAMES.get(self.type, self.type)
        if self.type == CLICK_IMAGE:
            kind = {(1, "left"): "Click", (2, "left"): "Double-click"}.get((self.clicks, self.button), "Right-click")
            base = f"{kind} on image"
        elif self.type == KEY:
            base = f"Press {self.keys or '?'}"
        elif self.type == TEXT:
            base = f'Type "{self.text}"'
        elif self.type == WAIT:
            base = f"Wait {self.seconds:g} s"
        elif self.type == CLICK_POINT:
            base = f"Click at ({self.point.x}, {self.point.y}) from anchor"
        return f"{base} — {self.label}" if self.label else base


@dataclass
class RunOptions:
    max_items: int = 100
    maximize_window: bool = False
    wait_list_change_s: float = 10.0
    pause_on_user_mouse: bool = True


@dataclass
class Flow:
    name: str = "New flow"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    schema_version: int = SCHEMA_VERSION
    monitor: MonitorInfo = field(default_factory=MonitorInfo)
    anchor_image: str | None = None
    anchor_confidence: float = 0.85
    first_row: FirstRow = field(default_factory=FirstRow)
    steps: list[Step] = field(default_factory=list)
    run: RunOptions = field(default_factory=RunOptions)
    last_run: str | None = None  # ISO timestamp + short result

    def is_ready(self) -> bool:
        return bool(self.anchor_image and self.first_row.offset.w and self.steps)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Flow:
        version = data.get("schema_version", SCHEMA_VERSION)
        if version > SCHEMA_VERSION:
            raise ValueError(f"This flow was made with a newer version of the app (schema {version}).")
        return _build(cls, data)


_NESTED = {
    "monitor": MonitorInfo,
    "first_row": FirstRow,
    "offset": Rect,
    "click_offset": Point,
    "point": Point,
    "run": RunOptions,
}


def _build(cls, data: dict):
    """Build a dataclass from a dict, ignoring unknown keys so older apps can read newer minor additions."""
    if not isinstance(data, dict):
        raise ValueError(f"Expected an object for {cls.__name__}")
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if f.name == "steps":
            value = [_build(Step, s) for s in value]
        elif f.name in _NESTED and value is not None:
            value = _build(_NESTED[f.name], value)
        kwargs[f.name] = value
    obj = cls(**kwargs)
    if isinstance(obj, Step) and obj.type not in STEP_TYPES:
        raise ValueError(f"Unknown step type: {obj.type}")
    return obj
