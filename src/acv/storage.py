"""Where flows, settings and logs live on disk, plus .acvflow import/export."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
import zipfile
from pathlib import Path

import cv2
import numpy as np

from . import APP_ID
from .model import IMAGE_STEPS, Flow

FLOW_FILE = "flow.json"
EXPORT_EXT = ".acvflow"
_SAFE_IMAGE = re.compile(r"^images/[A-Za-z0-9_-]+\.png$")


def data_dir() -> Path:
    """Roaming user data (flows, settings). ACV_DATA_DIR overrides it (tests, portable use)."""
    if os.environ.get("ACV_DATA_DIR"):
        base = Path(os.environ["ACV_DATA_DIR"])
    elif sys.platform == "win32":
        base = Path(os.environ["APPDATA"]) / APP_ID
    else:
        base = Path.home() / ".local" / "share" / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def logs_dir() -> Path:
    if os.environ.get("ACV_DATA_DIR"):
        path = Path(os.environ["ACV_DATA_DIR"]) / "logs"
    elif sys.platform == "win32":
        path = Path(os.environ["LOCALAPPDATA"]) / APP_ID / "logs"
    else:
        path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def flows_dir() -> Path:
    path = data_dir() / "flows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def flow_dir(flow: Flow | str) -> Path:
    flow_id = flow if isinstance(flow, str) else flow.id
    if not re.fullmatch(r"[0-9a-f]{32}", flow_id):
        raise ValueError(f"Invalid flow id: {flow_id!r}")
    return flows_dir() / flow_id


# --- images (cv2.imread/imwrite cannot handle non-ASCII paths on Windows) ---

def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Cannot read image: {path}")
    return img


def write_image(path: Path, img: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError(f"Cannot encode image: {path}")
    buf.tofile(str(path))


def load_flow_image(flow: Flow, name: str) -> np.ndarray:
    return read_image(flow_dir(flow) / name)


def add_flow_image(flow: Flow, img: np.ndarray, prefix: str) -> str:
    """Store an image in the flow folder and return its relative name."""
    name = f"images/{prefix}-{uuid.uuid4().hex[:8]}.png"
    write_image(flow_dir(flow) / name, img)
    return name


def _referenced_images(flow: Flow) -> set[str]:
    names = {flow.anchor_image, flow.first_row.empty_sample}
    names.update(s.image for s in flow.steps if s.type in IMAGE_STEPS)
    return {n for n in names if n}


# --- flows ---

def save_flow(flow: Flow) -> None:
    folder = flow_dir(flow)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / (FLOW_FILE + ".tmp")
    tmp.write_text(json.dumps(flow.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp, folder / FLOW_FILE)  # atomic: never leaves a half-written flow
    used = _referenced_images(flow)
    for img in (folder / "images").glob("*.png"):
        if f"images/{img.name}" not in used:
            img.unlink(missing_ok=True)


def load_flow(flow_id: str) -> Flow:
    path = flow_dir(flow_id) / FLOW_FILE
    flow = Flow.from_dict(json.loads(path.read_text(encoding="utf-8")))
    flow.id = flow_id
    return flow


def list_flows() -> list[Flow]:
    flows = []
    for folder in flows_dir().iterdir():
        if (folder / FLOW_FILE).is_file():
            try:
                flows.append(load_flow(folder.name))
            except Exception:  # a broken flow must not hide the others
                import logging
                logging.getLogger(__name__).exception("Skipping unreadable flow %s", folder)
    return sorted(flows, key=lambda f: f.name.lower())


def delete_flow(flow_id: str) -> None:
    shutil.rmtree(flow_dir(flow_id), ignore_errors=True)


def duplicate_flow(flow: Flow, new_name: str) -> Flow:
    copy = Flow.from_dict(flow.to_dict())
    copy.id = uuid.uuid4().hex
    copy.name = new_name
    copy.last_run = None
    shutil.copytree(flow_dir(flow), flow_dir(copy))
    save_flow(copy)
    return copy


def export_flow(flow: Flow, path: Path) -> None:
    folder = flow_dir(flow)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(FLOW_FILE, json.dumps(flow.to_dict(), indent=2))
        for name in sorted(_referenced_images(flow)):
            zf.write(folder / name, name)


def import_flow(path: Path) -> Flow:
    """Import a .acvflow file as a new flow. Rejects anything that is not flow.json or images/*.png."""
    with zipfile.ZipFile(path) as zf:
        try:
            flow = Flow.from_dict(json.loads(zf.read(FLOW_FILE).decode("utf-8")))
        except KeyError:
            raise ValueError("This file is not a valid flow (flow.json is missing).") from None
        names = _referenced_images(flow)
        for name in names:
            if not _SAFE_IMAGE.match(name):
                raise ValueError(f"Invalid image name in flow: {name!r}")
            if name not in zf.namelist():
                raise ValueError(f"Image missing from flow file: {name}")
        flow.id = uuid.uuid4().hex
        folder = flow_dir(flow)
        for name in names:
            img = cv2.imdecode(np.frombuffer(zf.read(name), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError(f"Corrupt image in flow file: {name}")
            write_image(folder / name, img)
    existing = {f.name for f in list_flows()}
    while flow.name in existing:
        flow.name += " (imported)"
    flow.last_run = None
    save_flow(flow)
    return flow


# --- settings ---

def load_settings() -> dict:
    path = data_dir() / "settings.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    (data_dir() / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
