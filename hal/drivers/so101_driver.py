from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hal.base_driver import BaseDriver

_PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"

DEFAULT_HOME = [0.0, -0.30, 0.60, 0.0, 0.0, 0.0]
REACH_ENVELOPE_M = 0.50
SHOULDER_OFFSET_LOCAL = (0.0, 0.0, 0.35)


class SO101Driver(BaseDriver):
    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        mock: bool = True,
        robot_id: str = "so101_001",
        base_pose_world: tuple[float, float, float] = (0.0, 0.0, 0.0),
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
        if not mock:
            self._connect_hardware()

    def _connect_hardware(self) -> None:
        raise NotImplementedError(
            "Real SO-101 hardware path is not wired up yet. "
            "Replace this with feetech / lerobot motor bus initialisation."
        )

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

    def _do_home(self, _params: dict) -> str:
        self._joint_angles = list(DEFAULT_HOME)
        self._end_effector_world = self._compute_end_effector_world()
        return f"home: joint_angles={self._joint_angles}"

    def _do_move_to_pose(self, params: dict) -> str:
        pose = params.get("pose")
        if not isinstance(pose, (list, tuple)) or len(pose) != 3:
            return "error: 'pose' must be a 3-element list [x, y, z]"
        if not self._within_reach(pose):
            return f"error: pose {list(pose)} is outside reach envelope ({REACH_ENVELOPE_M} m)"
        self._joint_angles = self._inverse_kinematics(pose)
        self._end_effector_world = tuple(float(v) for v in pose)
        if not self._mock:
            self._write_motor_targets(self._joint_angles)
        return f"moved to {list(pose)}"

    def _do_grasp(self, params: dict) -> str:
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
        if self._holding is None:
            return "error: nothing to release"
        released = self._holding
        self._holding = None
        self._gripper_state = "open"
        return f"released {released}"

    def _do_gripper_open(self, _params: dict) -> str:
        if self._holding is not None:
            return f"error: cannot open gripper while holding {self._holding!r}; use 'release' first"
        self._gripper_state = "open"
        return "gripper open"

    def _do_gripper_close(self, _params: dict) -> str:
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

    def _write_motor_targets(self, _joints: list[float]) -> None:
        raise NotImplementedError("Hardware motor write not wired up.")


SO101Driver._handlers = {
    "home": SO101Driver._do_home,
    "move_to_pose": SO101Driver._do_move_to_pose,
    "grasp": SO101Driver._do_grasp,
    "release": SO101Driver._do_release,
    "gripper_open": SO101Driver._do_gripper_open,
    "gripper_close": SO101Driver._do_gripper_close,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
