from __future__ import annotations

import json
from pathlib import Path

from hal.drivers import list_drivers, load_driver
from hal.drivers.so101_gesture_driver import SO101GestureDriver


def _write_identity(path: Path, payload: dict) -> None:
    path.write_text("```json\n" + json.dumps(payload, indent=2) + "\n```\n", encoding="utf-8")


def _scene() -> dict[str, dict]:
    return {
        "pharmacy_demo": {
            "workspace_clear": True,
            "human_hand_in_workspace": False,
        },
        "so101_counter_arm": {
            "status": "home",
            "emergency_stop": False,
            "wave_completed": False,
        },
    }


def test_so101_driver_registered() -> None:
    assert "so101_greeting" in list_drivers()
    assert "so101" in list_drivers()
    assert isinstance(load_driver("so101_greeting"), SO101GestureDriver)


def test_wave_blocked_until_identity_verified(tmp_path: Path) -> None:
    identity = tmp_path / "IDENTITY.md"
    _write_identity(
        identity,
        {
            "status": "not_checked",
            "age_verified": None,
        },
    )
    driver = SO101GestureDriver(identity_path=str(identity))
    driver.load_scene(_scene())
    driver.connect()

    result = driver.execute_action("wave", {"style": "friendly", "duration_sec": 1.0})

    assert result == "Error: SO-101 wave blocked: mock identity is not verified"
    scene = driver.get_scene()
    assert scene["so101_counter_arm"]["wave_completed"] is False


def test_wave_updates_scene_when_identity_verified(tmp_path: Path) -> None:
    identity = tmp_path / "IDENTITY.md"
    _write_identity(
        identity,
        {
            "status": "verified_mock",
            "patient_id": "P-1042",
            "name_match": True,
            "age_verified": True,
        },
    )
    driver = SO101GestureDriver(identity_path=str(identity), backend="dry_run")
    driver.load_scene(_scene())
    driver.connect()

    result = driver.execute_action("wave", {"style": "friendly", "duration_sec": 1.0})

    assert result == "SO-101 completed friendly wave."
    scene = driver.get_scene()
    assert scene["so101_counter_arm"]["wave_completed"] is True
    assert scene["so101_counter_arm"]["last_action"]["action_type"] == "wave"
    assert scene["so101_counter_arm"]["status"] == "home"
    runtime = driver.get_runtime_state()["robots"]["so101_counter_arm"]
    assert runtime["gesture_state"]["wave_completed"] is True


def test_wave_blocked_when_workspace_not_clear(tmp_path: Path) -> None:
    identity = tmp_path / "IDENTITY.md"
    _write_identity(identity, {"status": "verified_mock", "age_verified": True})
    scene = _scene()
    scene["pharmacy_demo"]["human_hand_in_workspace"] = True
    driver = SO101GestureDriver(identity_path=str(identity))
    driver.load_scene(scene)
    driver.connect()

    result = driver.execute_action("wave", {})

    assert result == "Error: SO-101 motion blocked: human hand is in workspace"
