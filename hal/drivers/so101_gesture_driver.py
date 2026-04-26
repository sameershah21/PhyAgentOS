"""SO-101 gesture-only HAL driver for the pharmacy verified-wave MVP."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hal.base_driver import BaseDriver

_PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _extract_json_block(text: str) -> dict[str, Any] | None:
    content = (text or "").strip()
    if not content:
        return None
    try:
        if "```json" in content:
            _, block = content.split("```json", 1)
            block, _ = block.split("```", 1)
            return json.loads(block)
        return json.loads(content)
    except (ValueError, json.JSONDecodeError):
        return None


class SO101GestureDriver(BaseDriver):
    """Gesture-only SO-101 driver with hard identity and workspace gates.

    The default backend is ``dry_run``: it validates state, records the intended
    trajectory, and updates ENVIRONMENT.md without touching hardware. Wire a real
    SO-101 SDK/serial backend behind ``run_trajectory`` once calibrated joint
    waypoints are available.
    """

    def __init__(
        self,
        gui: bool = False,
        *,
        robot_id: str = "so101_counter_arm",
        workspace: str | None = None,
        identity_path: str | None = None,
        backend: str = "dry_run",
        safe_home_joints: list[float] | None = None,
        safe_raise_joints: list[float] | None = None,
        safe_wave_left_joints: list[float] | None = None,
        safe_wave_right_joints: list[float] | None = None,
        **_kwargs: Any,
    ) -> None:
        self._gui = gui
        self.robot_id = str(robot_id or "so101_counter_arm").strip()
        self.workspace = Path(workspace).expanduser().resolve() if workspace else None
        self.identity_path = (
            Path(identity_path).expanduser().resolve()
            if identity_path
            else (self.workspace / "IDENTITY.md" if self.workspace else None)
        )
        self.backend = backend
        self._objects: dict[str, dict] = {}
        self._connected = False
        self._last_action: dict[str, Any] | None = None
        self._status = "home"
        self._wave_completed = False
        self._emergency_stop = False
        self._last_trajectory: list[dict[str, Any]] = []
        self._home_joints = safe_home_joints or [0.0, -0.7, 0.9, 0.0, 0.4, 0.0]
        self._raise_joints = safe_raise_joints or [0.0, -0.45, 0.75, 0.0, 0.85, 0.0]
        self._wave_left_joints = safe_wave_left_joints or [0.0, -0.45, 0.75, -0.25, 0.85, -0.35]
        self._wave_right_joints = safe_wave_right_joints or [0.0, -0.45, 0.75, 0.25, 0.85, 0.35]
        self._runtime_state = {"robots": {self.robot_id: self._make_robot_state()}}

    def get_profile_path(self) -> Path:
        return _PROFILES_DIR / "so101_greeting_arm.md"

    def load_scene(self, scene: dict[str, dict]) -> None:
        self._objects = dict(scene or {})
        arm = self._objects.get(self.robot_id) or self._objects.get("so101_counter_arm") or {}
        self._status = str(arm.get("status") or self._status)
        self._wave_completed = bool(arm.get("wave_completed", self._wave_completed))
        self._emergency_stop = bool(arm.get("emergency_stop", self._emergency_stop))
        self._refresh_runtime_state()

    def execute_action(self, action_type: str, params: dict) -> str:
        params = dict(params or {})
        try:
            self._validate_robot_id(params)
            if action_type == "connect_robot":
                self.connect()
                return "SO-101 greeting arm connected."
            if action_type == "check_connection":
                return "connected" if self.health_check() else "disconnected"
            if action_type == "home":
                return self.home()
            if action_type == "wave":
                return self.wave(
                    style=str(params.get("style", "friendly")),
                    duration_sec=float(params.get("duration_sec", params.get("duration_s", 2.0))),
                )
            if action_type == "acknowledge":
                return self.acknowledge(style=str(params.get("style", "small_wave")))
            if action_type == "stop":
                return self.stop(reason=str(params.get("reason", "unspecified")))
            return f"Unknown action: {action_type}"
        except Exception as exc:
            return f"Error: {exc}"

    def get_scene(self) -> dict[str, dict]:
        scene = dict(self._objects)
        scene[self.robot_id] = {
            "type": "tabletop_gesture_arm",
            "status": self._status,
            "last_action": self._last_action,
            "emergency_stop": self._emergency_stop,
            "wave_completed": self._wave_completed,
            "last_trajectory": self._last_trajectory,
            "backend": self.backend,
            "updated_at": _utc_now(),
        }
        return scene

    def connect(self) -> bool:
        self._connected = True
        self._refresh_runtime_state()
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._refresh_runtime_state()

    def is_connected(self) -> bool:
        return self._connected

    def health_check(self) -> bool:
        self._refresh_runtime_state()
        return self._connected

    def get_runtime_state(self) -> dict[str, Any]:
        self._refresh_runtime_state()
        return json.loads(json.dumps(self._runtime_state))

    def close(self) -> None:
        self.disconnect()

    def home(self) -> str:
        self._assert_no_emergency_stop()
        self.run_trajectory([self._waypoint("home", self._home_joints, 0.8)])
        self._status = "home"
        self._wave_completed = False
        self._record_action("home", {})
        return "SO-101 returned home."

    def wave(self, style: str = "friendly", duration_sec: float = 2.0) -> str:
        self._assert_identity_verified()
        self._assert_workspace_clear()
        self._assert_no_emergency_stop()
        duration_sec = max(0.5, min(float(duration_sec), 8.0))
        trajectory = self._wave_trajectory(style, duration_sec)
        self._status = "waving"
        self.run_trajectory(trajectory)
        self._status = "home"
        self._wave_completed = True
        self._record_action("wave", {"style": style, "duration_sec": duration_sec})
        return f"SO-101 completed {style} wave."

    def acknowledge(self, style: str = "small_wave") -> str:
        self._assert_workspace_clear()
        self._assert_no_emergency_stop()
        trajectory = [
            self._waypoint("raise_hand", self._raise_joints, 0.5),
            self._waypoint("acknowledge", self._wave_left_joints, 0.4),
            self._waypoint("home", self._home_joints, 0.6),
        ]
        self.run_trajectory(trajectory)
        self._status = "home"
        self._record_action("acknowledge", {"style": style})
        return f"SO-101 completed {style} acknowledgement."

    def stop(self, reason: str = "unspecified") -> str:
        self._status = "stopped"
        self._record_action("stop", {"reason": reason})
        self._refresh_runtime_state()
        return f"SO-101 stopped: {reason}"

    def run_trajectory(self, trajectory: list[dict[str, Any]]) -> None:
        if self.backend != "dry_run":
            raise RuntimeError(
                f"SO-101 backend {self.backend!r} is not implemented; use backend='dry_run' "
                "or wire a calibrated hardware trajectory runner."
            )
        self._last_trajectory = trajectory
        time.sleep(min(sum(float(p.get("duration", 0.0)) for p in trajectory), 0.05))

    def _wave_trajectory(self, style: str, duration_sec: float) -> list[dict[str, Any]]:
        if style == "small":
            left = self._blend(self._raise_joints, self._wave_left_joints, 0.45)
            right = self._blend(self._raise_joints, self._wave_right_joints, 0.45)
            cycles = 2
        elif style == "celebratory":
            left = self._wave_left_joints
            right = self._wave_right_joints
            cycles = 3
        else:
            left = self._blend(self._raise_joints, self._wave_left_joints, 0.75)
            right = self._blend(self._raise_joints, self._wave_right_joints, 0.75)
            cycles = 2
        segment = max(duration_sec / (2 + cycles * 2), 0.2)
        points = [
            self._waypoint("home", self._home_joints, segment),
            self._waypoint("raise_hand", self._raise_joints, segment),
        ]
        for i in range(cycles):
            points.append(self._waypoint(f"wave_left_{i + 1}", left, segment))
            points.append(self._waypoint(f"wave_right_{i + 1}", right, segment))
        points.append(self._waypoint("home", self._home_joints, segment))
        return points

    def _assert_identity_verified(self) -> None:
        identity = self._read_identity()
        if identity.get("status") != "verified_mock":
            raise RuntimeError("SO-101 wave blocked: mock identity is not verified")
        if identity.get("age_verified") is not True:
            raise RuntimeError("SO-101 wave blocked: age verification failed")

    def _assert_workspace_clear(self) -> None:
        demo = self._objects.get("pharmacy_demo", {})
        workspace_clear = demo.get("workspace_clear", True)
        hand_present = demo.get("human_hand_in_workspace", False)
        if workspace_clear is not True:
            raise RuntimeError("SO-101 motion blocked: workspace is not clear")
        if hand_present is True:
            raise RuntimeError("SO-101 motion blocked: human hand is in workspace")

    def _assert_no_emergency_stop(self) -> None:
        if self._emergency_stop:
            raise RuntimeError("SO-101 motion blocked: emergency stop is active")

    def _read_identity(self) -> dict[str, Any]:
        if self.identity_path is None or not self.identity_path.exists():
            return {}
        doc = _extract_json_block(self.identity_path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}

    def _validate_robot_id(self, params: dict[str, Any]) -> None:
        requested = str(params.get("robot_id", "")).strip()
        if requested and requested != self.robot_id:
            raise ValueError(f"robot_id mismatch: requested={requested}, configured={self.robot_id}")

    def _record_action(self, action_type: str, params: dict[str, Any]) -> None:
        self._last_action = {
            "action_type": action_type,
            "parameters": dict(params),
            "completed_at": _utc_now(),
        }
        self._refresh_runtime_state()

    def _refresh_runtime_state(self) -> None:
        self._runtime_state = {"robots": {self.robot_id: self._make_robot_state()}}

    def _make_robot_state(self) -> dict[str, Any]:
        return {
            "type": "so101_greeting_arm",
            "connection_state": {
                "status": "connected" if self._connected else "disconnected",
                "backend": self.backend,
                "last_heartbeat": _utc_now(),
                "last_error": None,
            },
            "gesture_state": {
                "status": self._status,
                "wave_completed": self._wave_completed,
                "emergency_stop": self._emergency_stop,
                "last_action": self._last_action,
            },
        }

    @staticmethod
    def _waypoint(name: str, joints: list[float], duration: float) -> dict[str, Any]:
        return {"name": name, "joints": list(joints), "duration": float(duration)}

    @staticmethod
    def _blend(a: list[float], b: list[float], amount: float) -> list[float]:
        return [float(x) + (float(y) - float(x)) * amount for x, y in zip(a, b)]
