import json

import pytest

from app.order_config import get_order_config, load_order_config


def test_shipped_config_is_valid():
    cfg = get_order_config()
    assert [t.number for t in cfg.tables] == [1, 2, 3]
    assert {p.code for p in cfg.products} == {"C1", "C2", "C3"}
    assert cfg.initial_status in cfg.statuses


def _write(tmp_path, **override):
    base = {
        "products": [{"code": "C1", "name": "Americano"}],
        "tables": [{"number": 1, "robot_destination": "MESA1", "distance_m": 1.0}],
        "statuses": ["A", "B"],
        "initial_status": "A",
        "dispatch_from": ["A"],
        "dispatched_status": "B",
    }
    base.update(override)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


def test_initial_status_must_be_listed(tmp_path):
    with pytest.raises(ValueError, match="'Z'"):
        load_order_config(_write(tmp_path, initial_status="Z"))


def test_dispatch_statuses_must_be_listed(tmp_path):
    with pytest.raises(ValueError, match="'Q'"):
        load_order_config(_write(tmp_path, dispatched_status="Q"))
    with pytest.raises(ValueError, match="'Q'"):
        load_order_config(_write(tmp_path, dispatch_from=["Q"]))


def test_duplicate_statuses_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        load_order_config(_write(tmp_path, statuses=["A", "A"]))


def test_comment_keys_are_ignored(tmp_path):
    cfg = load_order_config(_write(tmp_path, _comment="hello"))
    assert cfg.statuses == ["A", "B"]
