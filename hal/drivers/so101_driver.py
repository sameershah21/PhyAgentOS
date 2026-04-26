from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hal.base_driver import BaseDriver

_PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"

DEFAULT_HOME = [0.0, -0.30, 0.60, 0.0, 0.0, 0.0]
REACH_ENVELOPE_M = 0.50
SHOULDER_OFFSET_LOCAL = (0.0, 0.0, 0.35)

# SO-101 follower joint order — matches lerobot calibration JSON keys.
JOINT_NAMES = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)

DEFAULT_CALIBRATION_PATH = (
    Path.home()
    / ".cache"
    / "huggingface"
    / "lerobot"
    / "calibration"
    / "robots"
    / "so101_follower"
    / "so101_follower.json"
)


class SO101Driver(BaseDriver):
    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        mock: bool = True,
        robot_id: str = "so101_001",
        base_pose_world: tuple[float, float, float] = (0.0, 0.0, 0.0),
        calibration_path: str | Path | None = None,
        **_kwargs: Any,
    ) -> None:
        self._port = port
        self._mock = mock
        self.robot_id = robot_id
        self._base_pose_world = base_pose_world
        self._objects: dict[str, dict] = {}
        self._joint_angles = list(DEFAULT_HOME)
        self._gripper_state = "open"
        self._holding: str | None = None
        self._end_effector_world = self._compute_end_effector_world()
        self._bus = None
        self._connected = False
        self._calibration_path = (
            Path(calibration_path) if calibration_path else DEFAULT_CALIBRATION_PATH
        )
        if not mock:
            self._connect_hardware()

    def _connect_hardware(self) -> None:
        try:
            from lerobot.motors import Motor, MotorCalibration, MotorNormMode
            from lerobot.motors.feetech import FeetechMotorsBus
        except ImportError as exc:
            raise ImportError(
                "Real SO-101 hardware mode requires lerobot. "
                "Install the optional extra: pip install -e '.[so101]'"
            ) from exc

        if not self._calibration_path.exists():
            raise FileNotFoundError(
                f"SO-101 calibration not found at {self._calibration_path}. "
                "Run solo-cli calibration (or lerobot-calibrate) first."
            )

        with open(self._calibration_path) as f:
            calib_raw = json.load(f)

        calibration = {
            name: MotorCalibration(
                id=int(entry["id"]),
                drive_mode=int(entry["drive_mode"]),
                homing_offset=int(entry["homing_offset"]),
                range_min=int(entry["range_min"]),
                range_max=int(entry["range_max"]),
            )
            for name, entry in calib_raw.items()
        }

        motors = {
            name: Motor(
                id=calibration[name].id,
                model="sts3215",
                norm_mode=MotorNormMode.RANGE_M100_100,
            )
            for name in JOINT_NAMES
        }

        self._bus = FeetechMotorsBus(
            port=self._port,
            motors=motors,
            calibration=calibration,
        )
        self._bus.connect()
        self._connected = True

        positions = self._bus.sync_read("Present_Position")
        self._joint_angles = [float(positions[name]) for name in JOINT_NAMES]

    def get_profile_path(self) -> Path:
        return _PROFILES_DIR / "so101.md"

    def load_scene(self, scene: dict[str, dict]) -> None:
        self._objects = {k: dict(v) for k, v in scene.items()}

    def execute_action(self, action_type: str, params: dict) -> str:
        handler = self._handlers.get(action_type)
        if handler is None:
            return f"unknown action: {action_type}"
        try:
            return handler(self, params or {})
        except (KeyError, TypeError, ValueError) as exc:
            return f"error: {exc}"

    def get_scene(self) -> dict[str, dict]:
        scene = {k: dict(v) for k, v in self._objects.items()}
        if self._holding and self._holding in scene:
            scene[self._holding]["carried_by"] = self.robot_id
            scene[self._holding]["position"] = {
                "x": self._end_effector_world[0],
                "y": self._end_effector_world[1],
                "z": self._end_effector_world[2],
            }
        return scene

    def get_runtime_state(self) -> dict[str, Any]:
        if self._bus is not None and self._connected:
            try:
                live = self._bus.sync_read("Present_Position")
                self._joint_angles = [float(live[name]) for name in JOINT_NAMES]
            except Exception:
                pass
        return {
            "robots": {
                self.robot_id: {
                    "arm": {
                        "joint_angles_rad": list(self._joint_angles),
                        "gripper_state": self._gripper_state,
                        "holding": self._holding,
                        "end_effector_world": list(self._end_effector_world),
                        "stamp": _now_iso(),
                    }
                }
            }
        }

    def is_connected(self) -> bool:
        return self._mock or self._connected

    def close(self) -> None:
        if self._bus is not None and self._connected:
            try:
                self._bus.disconnect()
            finally:
                self._bus = None
                self._connected = False

    def _do_home(self, _params: dict) -> str:
        self._joint_angles = list(DEFAULT_HOME)
        self._end_effector_world = self._compute_end_effector_world()
        if not self._mock:
            self._write_motor_targets(self._joint_angles)
        return f"home: joint_angles={self._joint_angles}"

    def _do_move_to_pose(self, params: dict) -> str:
        if not self._mock:
            return (
                "error: move_to_pose not supported on real SO-101 hardware "
                "(no IK available); use 'move_to_joints' with explicit joint targets"
            )
        pose = params.get("pose")
        if not isinstance(pose, (list, tuple)) or len(pose) != 3:
            return "error: 'pose' must be a 3-element list [x, y, z]"
        if not self._within_reach(pose):
            return f"error: pose {list(pose)} is outside reach envelope ({REACH_ENVELOPE_M} m)"
        self._joint_angles = self._inverse_kinematics(pose)
        self._end_effector_world = tuple(float(v) for v in pose)
        return f"moved to {list(pose)}"

    def _do_move_to_joints(self, params: dict) -> str:
        joints = params.get("joints")
        if not isinstance(joints, (list, tuple)) or len(joints) != 6:
            return "error: 'joints' must be a 6-element list [j1..j6]"
        try:
            joints = [float(v) for v in joints]
        except (TypeError, ValueError):
            return "error: 'joints' values must be numeric"
        self._joint_angles = list(joints)
        if not self._mock:
            self._write_motor_targets(joints)
        return f"moved to joints {joints}"

    def _do_grasp(self, params: dict) -> str:
        if not self._mock:
            return (
                "error: grasp not supported on real SO-101 hardware "
                "(no IK available); use 'move_to_joints' to position the arm, then 'gripper_close'"
            )
        target_id = params.get("target_id")
        if not target_id:
            return "error: 'target_id' is required"
        if target_id not in self._objects:
            return f"error: target_id {target_id!r} not found in scene"
        if self._holding is not None:
            return f"error: gripper already holding {self._holding!r}"
        pose = params.get("pose") or self._object_pose(target_id)
        if pose is None:
            return f"error: no pose available for {target_id!r}"
        if not self._within_reach(pose):
            return f"error: target {target_id!r} at {pose} is outside reach envelope"
        move_result = self._do_move_to_pose({"pose": pose})
        if move_result.startswith("error:"):
            return move_result
        self._gripper_state = "closed"
        self._holding = target_id
        return f"grasped {target_id} at {list(pose)}"

    def _do_release(self, _params: dict) -> str:
        if not self._mock:
            return (
                "error: release not supported on real SO-101 hardware; "
                "use 'move_to_joints' to position the arm, then 'gripper_open'"
            )
        if self._holding is None:
            return "error: nothing to release"
        released = self._holding
        self._holding = None
        self._gripper_state = "open"
        return f"released {released}"

    def _do_gripper_open(self, _params: dict) -> str:
        if not self._mock:
            return (
                "error: gripper_open not supported on real SO-101 hardware; "
                "set the gripper joint via 'move_to_joints'"
            )
        if self._holding is not None:
            return f"error: cannot open gripper while holding {self._holding!r}; use 'release' first"
        self._gripper_state = "open"
        return "gripper open"

    def _do_gripper_close(self, _params: dict) -> str:
        if not self._mock:
            return (
                "error: gripper_close not supported on real SO-101 hardware; "
                "set the gripper joint via 'move_to_joints'"
            )
        self._gripper_state = "closed"
        return "gripper closed"

    _handlers: dict = {}

    def _within_reach(self, pose) -> bool:
        sx = self._base_pose_world[0] + SHOULDER_OFFSET_LOCAL[0]
        sy = self._base_pose_world[1] + SHOULDER_OFFSET_LOCAL[1]
        sz = self._base_pose_world[2] + SHOULDER_OFFSET_LOCAL[2]
        dx, dy, dz = pose[0] - sx, pose[1] - sy, pose[2] - sz
        return math.sqrt(dx * dx + dy * dy + dz * dz) <= REACH_ENVELOPE_M

    def _inverse_kinematics(self, _pose) -> list[float]:
        return list(DEFAULT_HOME)

    def _compute_end_effector_world(self) -> tuple[float, float, float]:
        bx, by, bz = self._base_pose_world
        return (bx + 0.30, by, bz + 0.45)

    def _object_pose(self, target_id: str) -> tuple[float, float, float] | None:
        obj = self._objects.get(target_id, {})
        pos = obj.get("position")
        if isinstance(pos, dict) and {"x", "y", "z"} <= pos.keys():
            return float(pos["x"]), float(pos["y"]), float(pos["z"])
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            return float(pos[0]), float(pos[1]), float(pos[2])
        return None

    def _write_motor_targets(self, joints: list[float]) -> None:
        if self._bus is None or not self._connected:
            raise RuntimeError("SO-101 hardware bus is not connected")
        targets = {name: float(value) for name, value in zip(JOINT_NAMES, joints)}
        self._bus.sync_write("Goal_Position", targets)


SO101Driver._handlers = {
    "home": SO101Driver._do_home,
    "move_to_pose": SO101Driver._do_move_to_pose,
    "move_to_joints": SO101Driver._do_move_to_joints,
    "grasp": SO101Driver._do_grasp,
    "release": SO101Driver._do_release,
    "gripper_open": SO101Driver._do_gripper_open,
    "gripper_close": SO101Driver._do_gripper_close,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
