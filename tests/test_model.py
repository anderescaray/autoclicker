import json
import zipfile

import numpy as np
import pytest

from acv import storage
from acv.model import CLICK_IMAGE, KEY, SCHEMA_VERSION, Flow, Point, Rect, Step


def make_flow():
    flow = Flow(name="Approve requests")
    img = np.random.default_rng(1).integers(0, 255, (20, 40, 3), dtype=np.uint8)
    flow.anchor_image = storage.add_flow_image(flow, img, "anchor")
    flow.first_row.offset = Rect(0, 30, 200, 20)
    flow.steps = [
        Step(type=CLICK_IMAGE, image=storage.add_flow_image(flow, img, "step"), click_offset=Point(5, 6), label="OK"),
        Step(type=KEY, keys="enter"),
    ]
    storage.save_flow(flow)
    return flow


def test_json_round_trip():
    flow = make_flow()
    again = Flow.from_dict(json.loads(json.dumps(flow.to_dict())))
    assert again == flow
    assert again.steps[0].click_offset == Point(5, 6)


def test_newer_schema_is_rejected():
    data = Flow().to_dict()
    data["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError):
        Flow.from_dict(data)


def test_unknown_step_type_is_rejected():
    data = Flow().to_dict()
    data["steps"] = [{"type": "format_disk"}]
    with pytest.raises(ValueError):
        Flow.from_dict(data)


def test_save_list_load_delete():
    flow = make_flow()
    assert [f.id for f in storage.list_flows()] == [flow.id]
    assert storage.load_flow(flow.id) == flow
    storage.delete_flow(flow.id)
    assert storage.list_flows() == []


def test_save_removes_unused_images():
    flow = make_flow()
    old = flow.steps[0].image
    flow.steps.pop(0)
    storage.save_flow(flow)
    assert not (storage.flow_dir(flow) / old).exists()
    assert (storage.flow_dir(flow) / flow.anchor_image).exists()


def test_duplicate_copies_images():
    flow = make_flow()
    copy = storage.duplicate_flow(flow, "Copy")
    assert copy.id != flow.id
    assert storage.load_flow_image(copy, copy.anchor_image).shape == (20, 40, 3)


def test_export_import(tmp_path):
    flow = make_flow()
    path = tmp_path / "x.acvflow"
    storage.export_flow(flow, path)
    imported = storage.import_flow(path)
    assert imported.id != flow.id
    assert imported.name == "Approve requests (imported)"
    assert len(imported.steps) == 2
    assert storage.load_flow_image(imported, imported.steps[0].image).shape == (20, 40, 3)


def test_import_rejects_path_traversal(tmp_path):
    data = Flow(anchor_image="../../evil.png").to_dict()
    path = tmp_path / "bad.acvflow"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("flow.json", json.dumps(data))
        zf.writestr("../../evil.png", b"x")
    with pytest.raises(ValueError):
        storage.import_flow(path)
    assert storage.list_flows() == []


def test_unicode_paths(tmp_path):
    img = np.zeros((5, 5, 3), np.uint8)
    path = tmp_path / "Iñaki çà" / "img.png"
    storage.write_image(path, img)
    assert storage.read_image(path).shape == (5, 5, 3)
