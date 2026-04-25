from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hal.drivers.so101_driver import SO101Driver


def _scene_with_bottle(target_id="bottle_02", pose=(0.30, 0.00, 0.45)):
    return {
        target_id: {
            "type": "prescription_bottle",
            "ocr_label": "Rx #1234",
            "position": {"x": pose[0], "y": pose[1], "z": pose[2]},
        }
    }


@pytest.fixture
def driver():
    d = SO101Driver(mock=True)
    yield d
    d.close()


@pytest.fixture
def driver_with_bottle(driver):
    driver.load_scene(_scene_with_bottle())
    return driver


class TestSO101DriverContract:
    def test_get_profile_path_returns_existing_file(self, driver):
        path = driver.get_profile_path()
        assert isinstance(path, Path)
        assert path.exists(), f"Profile file missing: {path}"

    def test_load_scene_empty_dict_does_not_raise(self, driver):
        driver.load_scene({})

    def test_get_scene_returns_dict(self, driver_with_bottle):
        assert isinstance(driver_with_bottle.get_scene(), dict)

    def test_execute_action_returns_string(self, driver):
        result = driver.execute_action("home", {})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unknown_action_returns_string_not_raise(self, driver):
        result = driver.execute_action("warp_to_mars", {})
        assert isinstance(result, str)
        assert "unknown" in result.lower()

    def test_close_is_idempotent(self, driver):
        driver.close()
        driver.close()


class TestSO101DriverBehavior:
    def test_home_resets_joint_angles(self, driver_with_bottle):
        driver_with_bottle.execute_action("move_to_pose", {"pose": [0.20, 0.10, 0.40]})
        result = driver_with_bottle.execute_action("home", {})
        assert result.startswith("home:")

    def test_move_to_pose_within_reach_succeeds(self, driver_with_bottle):
        result = driver_with_bottle.execute_action("move_to_pose", {"pose": [0.30, 0.0, 0.45]})
        assert result.startswith("moved to"), result

    def test_move_to_pose_out_of_reach_returns_error(self, driver_with_bottle):
        result = driver_with_bottle.execute_action("move_to_pose", {"pose": [5.0, 5.0, 5.0]})
        assert result.startswith("error:"), result
        assert "reach envelope" in result

    def test_move_to_pose_invalid_pose_returns_error(self, driver_with_bottle):
        result = driver_with_bottle.execute_action("move_to_pose", {"pose": [0.1, 0.2]})
        assert result.startswith("error:"), result

    def test_grasp_known_target_marks_holding(self, driver_with_bottle):
        result = driver_with_bottle.execute_action("grasp", {"target_id": "bottle_02"})
        assert result.startswith("grasped"), result
        arm = driver_with_bottle.get_runtime_state()["robots"]["so101_001"]["arm"]
        assert arm["holding"] == "bottle_02"
        assert arm["gripper_state"] == "closed"

    def test_grasp_unknown_target_returns_error(self, driver_with_bottle):
        result = driver_with_bottle.execute_action("grasp", {"target_id": "ghost_bottle"})
        assert result.startswith("error:"), result

    def test_grasp_when_already_holding_returns_error(self, driver_with_bottle):
        driver_with_bottle.execute_action("grasp", {"target_id": "bottle_02"})
        for k, v in _scene_with_bottle("bottle_03", (0.25, 0.10, 0.40)).items():
            driver_with_bottle._objects[k] = v
        result = driver_with_bottle.execute_action("grasp", {"target_id": "bottle_03"})
        assert result.startswith("error:"), result
        assert "already holding" in result

    def test_release_clears_holding(self, driver_with_bottle):
        driver_with_bottle.execute_action("grasp", {"target_id": "bottle_02"})
        result = driver_with_bottle.execute_action("release", {})
        assert result.startswith("released"), result
        arm = driver_with_bottle.get_runtime_state()["robots"]["so101_001"]["arm"]
        assert arm["holding"] is None
        assert arm["gripper_state"] == "open"

    def test_release_with_nothing_held_returns_error(self, driver_with_bottle):
        result = driver_with_bottle.execute_action("release", {})
        assert result.startswith("error:"), result

    def test_gripper_open_blocked_when_holding(self, driver_with_bottle):
        driver_with_bottle.execute_action("grasp", {"target_id": "bottle_02"})
        result = driver_with_bottle.execute_action("gripper_open", {})
        assert result.startswith("error:"), result

    def test_get_scene_after_grasp_attaches_object_to_robot(self, driver_with_bottle):
        driver_with_bottle.execute_action("grasp", {"target_id": "bottle_02"})
        scene = driver_with_bottle.get_scene()
        assert scene["bottle_02"]["carried_by"] == "so101_001"

    def test_real_hardware_path_raises_until_implemented(self):
        with pytest.raises(NotImplementedError):
            SO101Driver(mock=False)
