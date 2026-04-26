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

    def test_move_to_joints_mock_succeeds(self, driver):
        result = driver.execute_action(
            "move_to_joints", {"joints": [0.1, -0.2, 0.3, 0.0, 0.0, 0.0]}
        )
        assert result.startswith("moved to joints"), result
        arm = driver.get_runtime_state()["robots"]["so101_001"]["arm"]
        assert arm["joint_angles_rad"] == [0.1, -0.2, 0.3, 0.0, 0.0, 0.0]

    def test_move_to_joints_wrong_length_returns_error(self, driver):
        result = driver.execute_action("move_to_joints", {"joints": [0.0, 0.0, 0.0]})
        assert result.startswith("error:"), result
        assert "6-element" in result

    def test_move_to_joints_non_numeric_returns_error(self, driver):
        result = driver.execute_action(
            "move_to_joints", {"joints": ["a", "b", "c", "d", "e", "f"]}
        )
        assert result.startswith("error:"), result


class TestSO101DriverRealHardwareGating:
    """Real-hardware mode rejects actions that require IK or direct motor commands
    we don't have a safe default for. Driver is constructed with a fake bus so
    these tests don't need physical hardware."""

    @pytest.fixture
    def driver_real(self, monkeypatch):
        d = SO101Driver(mock=True)
        d._mock = False
        d._connected = True
        return d

    def test_move_to_pose_errors_on_real(self, driver_real):
        result = driver_real.execute_action("move_to_pose", {"pose": [0.30, 0.0, 0.45]})
        assert result.startswith("error:"), result
        assert "move_to_joints" in result

    def test_grasp_errors_on_real(self, driver_real):
        driver_real.load_scene(_scene_with_bottle())
        result = driver_real.execute_action("grasp", {"target_id": "bottle_02"})
        assert result.startswith("error:"), result
        assert "move_to_joints" in result

    def test_release_errors_on_real(self, driver_real):
        result = driver_real.execute_action("release", {})
        assert result.startswith("error:"), result
        assert "move_to_joints" in result

    def test_gripper_open_errors_on_real(self, driver_real):
        result = driver_real.execute_action("gripper_open", {})
        assert result.startswith("error:"), result
        assert "move_to_joints" in result

    def test_gripper_close_errors_on_real(self, driver_real):
        result = driver_real.execute_action("gripper_close", {})
        assert result.startswith("error:"), result
        assert "move_to_joints" in result

    def test_home_works_on_real_with_fake_bus(self, driver_real):
        class FakeBus:
            def __init__(self):
                self.writes = []
            def sync_write(self, name, values):
                self.writes.append((name, values))
        driver_real._bus = FakeBus()
        result = driver_real.execute_action("home", {})
        assert result.startswith("home:"), result
        assert driver_real._bus.writes == [
            ("Goal_Position", {
                "shoulder_pan": 0.0,
                "shoulder_lift": -0.30,
                "elbow_flex": 0.60,
                "wrist_flex": 0.0,
                "wrist_roll": 0.0,
                "gripper": 0.0,
            }),
        ]

    def test_move_to_joints_writes_targets_on_real(self, driver_real):
        class FakeBus:
            def __init__(self):
                self.writes = []
            def sync_write(self, name, values):
                self.writes.append((name, values))
        driver_real._bus = FakeBus()
        result = driver_real.execute_action(
            "move_to_joints", {"joints": [0.1, -0.2, 0.3, 0.4, -0.5, 0.6]}
        )
        assert result.startswith("moved to joints"), result
        assert driver_real._bus.writes == [
            ("Goal_Position", {
                "shoulder_pan": 0.1,
                "shoulder_lift": -0.2,
                "elbow_flex": 0.3,
                "wrist_flex": 0.4,
                "wrist_roll": -0.5,
                "gripper": 0.6,
            }),
        ]


class TestSO101DriverHardwareConnection:
    """Connection tests require lerobot installed and (optionally) hardware
    on a port supplied via SO101_TEST_PORT env var."""

    def test_connect_without_lerobot_raises_clear_error(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("lerobot"):
                raise ImportError("lerobot not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match=r"\[so101\]"):
            SO101Driver(mock=False)

    def test_connect_without_calibration_file_raises(self, tmp_path):
        pytest.importorskip("lerobot")
        missing = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError, match="calibration"):
            SO101Driver(mock=False, calibration_path=missing)
