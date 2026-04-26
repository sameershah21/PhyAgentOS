from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hal.drivers import list_drivers, load_driver
from hal.drivers.reachy_mini_driver import ReachyMiniDriver


class FakeStatus:
    def model_dump(self, mode: str = "json"):
        return {
            "type": "daemon_status",
            "robot_name": "reachy_mini",
            "state": "running",
            "mode": mode,
        }


class FakeClient:
    def __init__(self) -> None:
        self.disconnected = False

    def is_connected(self) -> bool:
        return not self.disconnected

    def disconnect(self) -> None:
        self.disconnected = True

    def get_status(self, wait: bool = True):
        return FakeStatus()


class FakeMedia:
    def __init__(self) -> None:
        self.closed = False
        self.sounds: list[str] = []
        self.frame = None

    def close(self) -> None:
        self.closed = True

    def play_sound(self, file_name: str) -> None:
        self.sounds.append(file_name)

    def get_frame(self):
        import numpy as np

        self.frame = np.zeros((2, 3, 3), dtype=np.uint8)
        return self.frame


class FakeReachyMini:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.media = FakeMedia()
        self.media_manager = self.media
        self.calls: list[tuple[str, dict]] = []
        self.imu = {"accelerometer": [0.0, 0.0, 9.8]}
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_args):
        self.exited = True
        self.media.close()
        self.client.disconnect()

    def get_current_joint_positions(self):
        return [0.0] * 7, [0.1, -0.1]

    def get_current_head_pose(self):
        class Pose:
            def tolist(self):
                return [
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ]

        return Pose()

    def goto_target(self, **kwargs):
        self.calls.append(("goto_target", kwargs))

    def set_target(self, **kwargs):
        self.calls.append(("set_target", kwargs))

    def set_target_head_pose(self, pose):
        self.calls.append(("set_target_head_pose", {"pose": pose}))

    def set_target_antenna_joint_positions(self, antennas):
        self.calls.append(("set_target_antenna_joint_positions", {"antennas": list(antennas)}))

    def set_target_body_yaw(self, body_yaw):
        self.calls.append(("set_target_body_yaw", {"body_yaw": body_yaw}))

    def wake_up(self):
        self.calls.append(("wake_up", {}))

    def goto_sleep(self):
        self.calls.append(("goto_sleep", {}))

    def enable_motors(self, ids=None):
        self.calls.append(("enable_motors", {"ids": ids}))

    def disable_motors(self, ids=None):
        self.calls.append(("disable_motors", {"ids": ids}))

    def enable_gravity_compensation(self):
        self.calls.append(("enable_gravity_compensation", {}))

    def disable_gravity_compensation(self):
        self.calls.append(("disable_gravity_compensation", {}))

    def set_automatic_body_yaw(self, enabled: bool):
        self.calls.append(("set_automatic_body_yaw", {"enabled": enabled}))

    def play_move(self, move, initial_goto_duration: float = 1.0):
        self.calls.append(("play_move", {"move": move, "initial_goto_duration": initial_goto_duration}))


def _driver_with_fake_robot(monkeypatch):
    fake = FakeReachyMini()
    driver = ReachyMiniDriver(robot_id="reachy_mini_test", connection_mode="localhost_only")
    monkeypatch.setattr(driver, "_build_robot", lambda: fake)
    return driver, fake


def test_reachy_mini_driver_registered() -> None:
    assert "reachy_mini" in list_drivers()
    driver = load_driver("reachy_mini", robot_id="reachy_mini_test")
    assert isinstance(driver, ReachyMiniDriver)


def test_connect_refreshes_runtime_state(monkeypatch) -> None:
    driver, _fake = _driver_with_fake_robot(monkeypatch)

    assert driver.execute_action("connect_robot", {}) == "Robot connection established."
    assert _fake.entered is True

    robot_state = driver.get_runtime_state()["robots"]["reachy_mini_test"]
    assert robot_state["connection_state"]["status"] == "connected"
    assert robot_state["joint_state"]["antennas_rad"] == [0.1, -0.1]
    assert robot_state["joint_state"]["antenna_left_rad"] == -0.1
    assert robot_state["joint_state"]["antenna_right_rad"] == 0.1
    assert robot_state["daemon_status"]["state"] == "running"
    assert robot_state["imu"]["accelerometer"] == [0.0, 0.0, 9.8]


def test_set_antennas_converts_degrees_and_uses_goto(monkeypatch) -> None:
    driver, fake = _driver_with_fake_robot(monkeypatch)

    result = driver.execute_action(
        "set_antennas",
        {"antennas": [90, -90], "duration_s": 0.25, "degrees": True},
    )

    assert result == "Reachy Mini antennas updated."
    name, kwargs = fake.calls[-1]
    assert name == "goto_target"
    assert kwargs["antennas"] == [1.5707963267948966, -1.5707963267948966]
    assert kwargs["duration"] == 0.25


def test_set_antennas_prefers_named_left_right(monkeypatch) -> None:
    driver, fake = _driver_with_fake_robot(monkeypatch)

    result = driver.execute_action(
        "set_antennas",
        {"left": 45, "right": -30, "duration_s": 0.25, "degrees": True},
    )

    assert result == "Reachy Mini antennas updated."
    name, kwargs = fake.calls[-1]
    assert name == "goto_target"
    assert kwargs["antennas"] == [-0.5235987755982988, 0.7853981633974483]


def test_set_target_accepts_pose_matrix_without_sdk_utils(monkeypatch) -> None:
    driver, fake = _driver_with_fake_robot(monkeypatch)
    pose = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]

    result = driver.execute_action(
        "set_target",
        {
            "head_pose_matrix": pose,
            "antennas": [0.0, 0.0],
            "body_yaw": 30,
            "degrees": True,
        },
    )

    assert result == "Reachy Mini action set_target completed."
    name, kwargs = fake.calls[-1]
    assert name == "set_target"
    assert kwargs["antennas"] == [0.0, 0.0]
    assert kwargs["body_yaw"] == 0.5235987755982988


def test_set_head_pose_uses_dedicated_sdk_method(monkeypatch) -> None:
    driver, fake = _driver_with_fake_robot(monkeypatch)
    pose = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]

    result = driver.execute_action("set_head_pose", {"head_pose_matrix": pose})

    assert result == "Reachy Mini action set_head_pose completed."
    assert fake.calls[-1][0] == "set_target_head_pose"


def test_wake_up_enables_motors_first(monkeypatch) -> None:
    driver, fake = _driver_with_fake_robot(monkeypatch)

    result = driver.execute_action("wake_up", {})

    assert result == "Reachy Mini woke up."
    assert fake.calls[:2] == [
        ("enable_motors", {"ids": None}),
        ("wake_up", {}),
    ]


def test_capture_frame_saves_npy_and_updates_scene(monkeypatch, tmp_path: Path) -> None:
    driver, _fake = _driver_with_fake_robot(monkeypatch)
    output = tmp_path / "frame.npy"

    result = driver.execute_action("capture_frame", {"output_path": str(output)})

    assert result == f"Reachy Mini camera frame saved to {output}"
    assert output.exists()
    scene = driver.get_scene()
    assert scene["reachy_mini_camera"]["path"] == str(output)
    assert scene["reachy_mini_camera"]["shape"] == [2, 3, 3]


def test_play_recorded_move(monkeypatch) -> None:
    driver, fake = _driver_with_fake_robot(monkeypatch)

    class FakeRecordedMoves:
        def __init__(self, library: str) -> None:
            self.library = library

        def get(self, name: str):
            return {"library": self.library, "name": name}

    recorded_move_mod = types.ModuleType("reachy_mini.motion.recorded_move")
    recorded_move_mod.RecordedMoves = FakeRecordedMoves
    motion_mod = types.ModuleType("reachy_mini.motion")
    reachy_mod = types.ModuleType("reachy_mini")
    monkeypatch.setitem(sys.modules, "reachy_mini", reachy_mod)
    monkeypatch.setitem(sys.modules, "reachy_mini.motion", motion_mod)
    monkeypatch.setitem(sys.modules, "reachy_mini.motion.recorded_move", recorded_move_mod)

    result = driver.execute_action(
        "play_recorded_move",
        {"library": "demo/library", "name": "wave", "initial_goto_duration": 0.4},
    )

    assert result == "Reachy Mini played recorded move 'wave' from 'demo/library'."
    name, kwargs = fake.calls[-1]
    assert name == "play_move"
    assert kwargs["move"] == {"library": "demo/library", "name": "wave"}
    assert kwargs["initial_goto_duration"] == 0.4


def test_robot_id_mismatch_rejected(monkeypatch) -> None:
    driver, _fake = _driver_with_fake_robot(monkeypatch)

    result = driver.execute_action("wake_up", {"robot_id": "wrong"})

    assert result.startswith("Error: robot_id mismatch:")


def test_disconnect_closes_client_and_media(monkeypatch) -> None:
    driver, fake = _driver_with_fake_robot(monkeypatch)
    assert driver.execute_action("connect_robot", {}) == "Robot connection established."

    assert driver.execute_action("disconnect_robot", {}) == "Robot connection closed."

    assert fake.client.disconnected is True
    assert fake.media.closed is True
    assert fake.exited is True
    state = driver.get_runtime_state()["robots"]["reachy_mini_test"]
    assert state["connection_state"]["status"] == "disconnected"
