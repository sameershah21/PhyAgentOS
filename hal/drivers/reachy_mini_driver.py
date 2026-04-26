"""Reachy Mini HAL driver backed by the official ``reachy_mini`` SDK."""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from hal.base_driver import BaseDriver

_PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


Interpolation = Literal["linear", "minjerk", "ease_in_out", "cartoon"]


@dataclass(frozen=True)
class HeadPose:
    """Reachy Mini 6-DOF head target.

    Translations are meters by default. Rotations are radians internally.
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0

    def to_matrix(self):
        from reachy_mini.utils import create_head_pose

        return create_head_pose(
            x=self.x,
            y=self.y,
            z=self.z,
            roll=self.roll,
            pitch=self.pitch,
            yaw=self.yaw,
            mm=False,
            degrees=False,
        )


@dataclass(frozen=True)
class AntennaTargets:
    """Named antenna targets.

    Reachy Mini SDK wire order is [right, left]. This type lets the HAL
    use side names internally and only convert at the SDK boundary.
    """

    left: float = 0.0
    right: float = 0.0

    def to_sdk_list(self) -> list[float]:
        return [self.right, self.left]

    @classmethod
    def from_sdk_list(cls, antennas: list[float]) -> "AntennaTargets":
        if len(antennas) != 2:
            raise ValueError(f"expected length-2 antenna list, got {antennas!r}")
        return cls(left=float(antennas[1]), right=float(antennas[0]))


class ReachyMiniDriver(BaseDriver):
    """Control a Reachy Mini through the official client/server SDK."""

    def __init__(
        self,
        gui: bool = False,
        *,
        robot_id: str = "reachy_mini_001",
        host: str = "reachy-mini.local",
        port: int = 8000,
        connection_mode: str = "auto",
        spawn_daemon: bool = False,
        use_sim: bool = False,
        timeout: float = 5.0,
        media_backend: str = "no_media",
        automatic_body_yaw: bool = True,
        reconnect_policy: str = "manual",
        sdk_factory: Any | None = None,
        **_kwargs: Any,
    ) -> None:
        self._gui = gui
        self.robot_id = str(robot_id or "reachy_mini_001").strip()
        self.host = host
        self.port = int(port)
        self.connection_mode = connection_mode
        self.spawn_daemon = bool(spawn_daemon)
        self.use_sim = bool(use_sim)
        self.timeout = float(timeout)
        self.media_backend = media_backend
        self.automatic_body_yaw = bool(automatic_body_yaw)
        self.reconnect_policy = reconnect_policy
        self._sdk_factory = sdk_factory

        self._objects: dict[str, dict] = {}
        self._robot: Any | None = None
        self._robot_entered = False
        self._last_action: dict[str, Any] | None = None
        self._runtime_state = {"robots": {self.robot_id: self._make_robot_state()}}

    def get_profile_path(self) -> Path:
        return _PROFILES_DIR / "reachy_mini.md"

    def load_scene(self, scene: dict[str, dict]) -> None:
        self._objects = dict(scene or {})

    def execute_action(self, action_type: str, params: dict) -> str:
        params = dict(params or {})
        try:
            self._validate_robot_id(params)
            if action_type == "connect_robot":
                return "Robot connection established." if self.connect() else self._connection_error()
            if action_type == "check_connection":
                return "connected" if self.health_check() else "disconnected"
            if action_type == "disconnect_robot":
                self.disconnect()
                return "Robot connection closed."
            if action_type == "get_state":
                self._refresh_runtime_snapshot()
                return "State refreshed."

            if action_type in ("wake_up", "goto_sleep"):
                return self._execute_lifecycle(action_type)
            if action_type in ("goto_target", "set_target", "set_head_pose"):
                return self._execute_target(action_type, params)
            if action_type == "set_antennas":
                return self._execute_antennas(params)
            if action_type == "set_body_yaw":
                return self._execute_body_yaw(params)
            if action_type == "look_at_world":
                return self._execute_look_at_world(params)
            if action_type == "look_at_image":
                return self._execute_look_at_image(params)
            if action_type == "play_sound":
                return self._execute_play_sound(params)
            if action_type == "capture_frame":
                return self._execute_capture_frame(params)
            if action_type == "play_recorded_move":
                return self._execute_play_recorded_move(params)
            if action_type in (
                "enable_motors",
                "disable_motors",
                "enable_gravity_compensation",
                "disable_gravity_compensation",
            ):
                return self._execute_motor_mode(action_type, params)
            if action_type == "set_automatic_body_yaw":
                return self._execute_automatic_body_yaw(params)

            return f"Unknown action: {action_type}"
        except ValueError as exc:
            return self._error_result(str(exc))
        except Exception as exc:
            return self._error_result(f"{action_type} failed: {type(exc).__name__}: {exc}")

    def get_scene(self) -> dict[str, dict]:
        scene = dict(self._objects)
        scene["reachy_mini_runtime"] = {
            "robot_id": self.robot_id,
            "host": self.host,
            "port": self.port,
            "connection_mode": self.connection_mode,
            "media_backend": self.media_backend,
            "last_action": copy.deepcopy(self._last_action),
        }
        return scene

    def connect(self) -> bool:
        if self.is_connected():
            self._set_connection_status("connected", last_error=None)
            self._refresh_runtime_snapshot()
            return True

        try:
            self._robot = self._build_robot()
            enter = getattr(self._robot, "__enter__", None)
            if callable(enter):
                entered = enter()
                if entered is not None:
                    self._robot = entered
                self._robot_entered = True
            self._set_connection_status("connected", last_error=None)
            self._refresh_runtime_snapshot()
            return True
        except Exception as exc:
            self._robot = None
            self._robot_entered = False
            self._set_connection_status("error", last_error=str(exc))
            return False

    def disconnect(self) -> None:
        robot = self._robot
        self._robot = None
        entered = self._robot_entered
        self._robot_entered = False
        if robot is not None:
            if entered and callable(getattr(robot, "__exit__", None)):
                try:
                    robot.__exit__(None, None, None)
                except Exception:
                    pass
            else:
                try:
                    media = getattr(robot, "media_manager", None)
                    if media is not None and hasattr(media, "close"):
                        media.close()
                except Exception:
                    pass
                try:
                    client = getattr(robot, "client", None)
                    if client is not None and hasattr(client, "disconnect"):
                        client.disconnect()
                except Exception:
                    pass
        self._set_connection_status("disconnected", last_error=None)

    def is_connected(self) -> bool:
        if self._robot is None:
            return False
        client = getattr(self._robot, "client", None)
        if client is None:
            return True
        try:
            checker = getattr(client, "is_connected", None)
            if callable(checker):
                return bool(checker())
            return bool(getattr(client, "_is_alive", True))
        except Exception:
            return False

    def health_check(self) -> bool:
        if not self.is_connected():
            self._set_connection_status("disconnected", last_error="disconnected")
            if self.reconnect_policy == "auto":
                return self.connect()
            return False
        self._set_connection_status("connected", last_error=None)
        self._refresh_runtime_snapshot()
        return True

    def get_runtime_state(self) -> dict[str, Any]:
        return copy.deepcopy(self._runtime_state)

    def close(self) -> None:
        self.disconnect()

    def _build_robot(self) -> Any:
        if self._sdk_factory is not None:
            return self._sdk_factory()

        try:
            from reachy_mini import ReachyMini
        except ImportError as exc:
            raise RuntimeError(
                "reachy-mini SDK is not installed in this Python environment. "
                "Install with Python >=3.10: python -m pip install reachy-mini"
            ) from exc

        return ReachyMini(
            host=self.host,
            port=self.port,
            connection_mode=self.connection_mode,
            spawn_daemon=self.spawn_daemon,
            use_sim=self.use_sim,
            timeout=self.timeout,
            automatic_body_yaw=self.automatic_body_yaw,
            media_backend=self.media_backend,
        )

    def _validate_robot_id(self, params: dict[str, Any]) -> None:
        requested = str(params.get("robot_id", "")).strip()
        if requested and requested != self.robot_id:
            raise ValueError(
                f"robot_id mismatch: requested={requested}, configured={self.robot_id}"
            )

    def _require_robot(self) -> Any:
        if not self.is_connected():
            if not self.connect():
                raise RuntimeError(self._connection_error())
        assert self._robot is not None
        return self._robot

    def _execute_lifecycle(self, action_type: str) -> str:
        robot = self._require_robot()
        if action_type == "wake_up":
            enable = getattr(robot, "enable_motors", None)
            if callable(enable):
                enable()
            robot.wake_up()
            self._record_action(action_type, {})
            self._refresh_runtime_snapshot()
            return "Reachy Mini woke up."
        robot.goto_sleep()
        self._record_action(action_type, {})
        self._refresh_runtime_snapshot()
        return "Reachy Mini went to sleep."

    def _execute_target(self, action_type: str, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        pose = self._optional_pose_from_params(params)
        if action_type == "set_head_pose" and pose is None:
            raise ValueError("set_head_pose requires pose fields or head_pose_matrix.")
        antennas = self._optional_antennas(params)
        body_yaw = self._optional_angle(params, "body_yaw")

        if action_type == "set_head_pose":
            setter = getattr(robot, "set_target_head_pose", None)
            if callable(setter):
                setter(pose)
            else:
                robot.set_target(head=pose)
        elif action_type == "set_target":
            robot.set_target(head=pose, antennas=antennas, body_yaw=body_yaw)
        else:
            duration = max(float(params.get("duration_s", params.get("duration", 0.5))), 0.05)
            method = self._interpolation_method(str(params.get("method", "minjerk")))
            robot.goto_target(
                head=pose,
                antennas=antennas,
                body_yaw=body_yaw,
                duration=duration,
                method=method,
            )

        self._record_action(action_type, params)
        self._refresh_runtime_snapshot()
        return f"Reachy Mini action {action_type} completed."

    def _execute_antennas(self, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        antennas = self._required_antennas(params)
        if bool(params.get("smooth", True)):
            duration = max(float(params.get("duration_s", params.get("duration", 0.5))), 0.05)
            robot.goto_target(antennas=antennas, duration=duration, body_yaw=None)
        else:
            setter = getattr(robot, "set_target_antenna_joint_positions", None)
            if callable(setter):
                setter(antennas)
            else:
                robot.set_target(antennas=antennas)
        self._record_action("set_antennas", params)
        self._refresh_runtime_snapshot()
        return "Reachy Mini antennas updated."

    def _execute_body_yaw(self, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        body_yaw = self._optional_angle(params, "body_yaw")
        if body_yaw is None:
            raise ValueError("body_yaw is required.")
        if bool(params.get("smooth", True)):
            duration = max(float(params.get("duration_s", params.get("duration", 0.5))), 0.05)
            robot.goto_target(body_yaw=body_yaw, duration=duration)
        else:
            setter = getattr(robot, "set_target_body_yaw", None)
            if callable(setter):
                setter(body_yaw)
            else:
                robot.set_target(body_yaw=body_yaw)
        self._record_action("set_body_yaw", params)
        self._refresh_runtime_snapshot()
        return "Reachy Mini body yaw updated."

    def _execute_look_at_world(self, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        x = float(params["x"])
        y = float(params["y"])
        z = float(params["z"])
        duration = float(params.get("duration_s", params.get("duration", 1.0)))
        robot.look_at_world(x=x, y=y, z=z, duration=duration, perform_movement=True)
        self._record_action("look_at_world", params)
        self._refresh_runtime_snapshot()
        return "Reachy Mini look_at_world completed."

    def _execute_look_at_image(self, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        u = int(params["u"])
        v = int(params["v"])
        duration = float(params.get("duration_s", params.get("duration", 1.0)))
        robot.look_at_image(u=u, v=v, duration=duration, perform_movement=True)
        self._record_action("look_at_image", params)
        self._refresh_runtime_snapshot()
        return "Reachy Mini look_at_image completed."

    def _execute_play_sound(self, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        file_name = str(params.get("file") or params.get("sound") or "").strip()
        if not file_name:
            raise ValueError("play_sound requires file or sound.")
        robot.media.play_sound(file_name)
        self._record_action("play_sound", params)
        return f"Reachy Mini playing sound: {file_name}"

    def _execute_capture_frame(self, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        output_path = Path(str(params.get("output_path") or "reachy_mini_frame.npy")).expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        frame = robot.media.get_frame()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        suffix = output_path.suffix.lower()
        if suffix == ".npy":
            import numpy as np

            np.save(output_path, frame)
        elif suffix in {".png", ".jpg", ".jpeg"}:
            self._write_image(output_path, frame)
        else:
            raise ValueError("capture_frame output_path must end with .npy, .png, .jpg, or .jpeg")

        self._record_action("capture_frame", params)
        scene_entry = self._objects.setdefault("reachy_mini_camera", {})
        scene_entry.update(
            {
                "type": "camera_frame",
                "robot_id": self.robot_id,
                "path": str(output_path),
                "captured_at": _utc_now(),
                "shape": list(getattr(frame, "shape", [])),
            }
        )
        return f"Reachy Mini camera frame saved to {output_path}"

    def _execute_play_recorded_move(self, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        name = str(params.get("name") or params.get("move_name") or "").strip()
        library = str(params.get("library") or params.get("dataset") or "").strip()
        if not name or not library:
            raise ValueError("play_recorded_move requires name and library.")
        initial_goto_duration = float(params.get("initial_goto_duration", 1.0))

        from reachy_mini.motion.recorded_move import RecordedMoves

        moves = RecordedMoves(library)
        robot.play_move(moves.get(name), initial_goto_duration=initial_goto_duration)
        self._record_action("play_recorded_move", params)
        self._refresh_runtime_snapshot()
        return f"Reachy Mini played recorded move {name!r} from {library!r}."

    def _execute_motor_mode(self, action_type: str, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        ids = params.get("ids")
        if ids is not None and not isinstance(ids, list):
            raise ValueError("ids must be a list of motor names when provided.")
        if action_type == "enable_motors":
            robot.enable_motors(ids=ids)
        elif action_type == "disable_motors":
            robot.disable_motors(ids=ids)
        elif action_type == "enable_gravity_compensation":
            robot.enable_gravity_compensation()
        else:
            robot.disable_gravity_compensation()
        self._record_action(action_type, params)
        self._refresh_runtime_snapshot()
        return f"Reachy Mini motor action {action_type} completed."

    def _execute_automatic_body_yaw(self, params: dict[str, Any]) -> str:
        robot = self._require_robot()
        enabled = bool(params.get("enabled", True))
        robot.set_automatic_body_yaw(enabled)
        self._record_action("set_automatic_body_yaw", params)
        self._refresh_runtime_snapshot()
        return f"Reachy Mini automatic body yaw set to {enabled}."

    @staticmethod
    def _angle(value: Any, *, degrees: bool) -> float:
        angle = float(value)
        return math.radians(angle) if degrees else angle

    def _optional_angle(self, params: dict[str, Any], key: str) -> float | None:
        if key not in params or params[key] is None:
            return None
        return self._angle(params[key], degrees=bool(params.get("degrees", True)))

    def _optional_antennas(self, params: dict[str, Any]) -> list[float] | None:
        targets = self._optional_antenna_targets(params)
        return targets.to_sdk_list() if targets is not None else None

    def _required_antennas(self, params: dict[str, Any]) -> list[float]:
        targets = self._optional_antenna_targets(params)
        if targets is None:
            raise ValueError("set_antennas requires left/right or antennas=[right,left].")
        return targets.to_sdk_list()

    def _optional_antenna_targets(self, params: dict[str, Any]) -> AntennaTargets | None:
        degrees = bool(params.get("degrees", True))
        if "left" in params or "right" in params:
            if params.get("left") is None or params.get("right") is None:
                raise ValueError("set_antennas requires both left and right when using named parameters.")
            return AntennaTargets(
                left=self._angle(params["left"], degrees=degrees),
                right=self._angle(params["right"], degrees=degrees),
            )
        raw = params.get("antennas")
        if raw is None:
            return None
        values = self._coerce_antennas(raw, degrees=degrees)
        return AntennaTargets.from_sdk_list(values)

    def _optional_pose_from_params(self, params: dict[str, Any]) -> Any | None:
        pose_keys = {"head_pose_matrix", "x", "y", "z", "roll", "pitch", "yaw"}
        if not any(key in params for key in pose_keys):
            return None
        return self._pose_from_params(params)

    def _pose_from_params(self, params: dict[str, Any]) -> Any:
        if "head_pose_matrix" in params:
            import numpy as np

            pose = np.array(params["head_pose_matrix"], dtype=float)
            if pose.shape == (16,):
                pose = pose.reshape((4, 4))
            if pose.shape != (4, 4):
                raise ValueError("head_pose_matrix must be 4x4 or flattened length 16.")
            return pose

        degrees = bool(params.get("degrees", True))
        scale = 0.001 if bool(params.get("mm", False)) else 1.0
        return HeadPose(
            x=float(params.get("x", 0.0)) * scale,
            y=float(params.get("y", 0.0)) * scale,
            z=float(params.get("z", 0.0)) * scale,
            roll=self._angle(params.get("roll", 0.0), degrees=degrees),
            pitch=self._angle(params.get("pitch", 0.0), degrees=degrees),
            yaw=self._angle(params.get("yaw", 0.0), degrees=degrees),
        ).to_matrix()

    @staticmethod
    def _coerce_antennas(raw: Any, *, degrees: bool) -> list[float]:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ValueError("antennas must be a two-element list [right, left].")
        vals = [float(raw[0]), float(raw[1])]
        return [math.radians(v) for v in vals] if degrees else vals

    @staticmethod
    def _interpolation_method(method: str) -> Any:
        try:
            from reachy_mini.utils.interpolation import InterpolationTechnique

            return InterpolationTechnique(method)
        except Exception:
            return method

    def _refresh_runtime_snapshot(self) -> None:
        state = self._robot_state()
        robot = self._robot
        state["updated_at"] = _utc_now()
        if robot is None:
            return
        try:
            head_joints, antennas = robot.get_current_joint_positions()
            antenna_targets = AntennaTargets.from_sdk_list(list(antennas))
            state["joint_state"] = {
                "head_joints_rad": list(head_joints),
                "antennas_rad": list(antennas),
                "antenna_left_rad": antenna_targets.left,
                "antenna_right_rad": antenna_targets.right,
            }
        except Exception as exc:
            state["joint_state"] = {"error": str(exc)}
        try:
            pose = robot.get_current_head_pose()
            state["robot_pose"]["head_pose_matrix"] = pose.tolist()
        except Exception as exc:
            state["robot_pose"]["head_pose_error"] = str(exc)
        try:
            imu = getattr(robot, "imu", None)
            if imu is not None:
                state["imu"] = imu
        except Exception as exc:
            state["imu"] = {"error": str(exc)}
        try:
            status = robot.client.get_status(wait=False)
            dump = status.model_dump(mode="json") if hasattr(status, "model_dump") else dict(status)
            state["daemon_status"] = dump
        except Exception:
            pass

    def _make_robot_state(self) -> dict[str, Any]:
        return {
            "type": "reachy_mini",
            "connection_state": {
                "status": "disconnected",
                "host": self.host,
                "port": self.port,
                "connection_mode": self.connection_mode,
                "last_heartbeat": None,
                "last_error": None,
            },
            "robot_pose": {
                "frame": "reachy_mini_base",
                "body_yaw_rad": None,
                "head_pose_matrix": None,
            },
            "joint_state": {
                "head_joints_rad": None,
                "antennas_rad": None,
            },
            "last_action": None,
        }

    def _robot_state(self) -> dict[str, Any]:
        robots = self._runtime_state.setdefault("robots", {})
        if self.robot_id not in robots:
            robots[self.robot_id] = self._make_robot_state()
        return robots[self.robot_id]

    def _set_connection_status(self, status: str, *, last_error: str | None) -> None:
        conn = self._robot_state().setdefault("connection_state", {})
        conn.update(
            {
                "status": status,
                "host": self.host,
                "port": self.port,
                "connection_mode": self.connection_mode,
                "last_error": last_error,
            }
        )
        if status == "connected":
            conn["last_heartbeat"] = _utc_now()

    def _record_action(self, action_type: str, params: dict[str, Any]) -> None:
        self._last_action = {
            "action_type": action_type,
            "parameters": copy.deepcopy(params),
            "timestamp": _utc_now(),
        }
        self._robot_state()["last_action"] = copy.deepcopy(self._last_action)

    def _connection_error(self) -> str:
        err = self._robot_state().get("connection_state", {}).get("last_error")
        return f"Connection error: {err or 'not connected'}"

    def _error_result(self, message: str) -> str:
        self._set_connection_status(
            self._robot_state().get("connection_state", {}).get("status", "error"),
            last_error=message,
        )
        return f"Error: {message}"

    @staticmethod
    def _write_image(path: Path, frame: Any) -> None:
        try:
            from PIL import Image

            Image.fromarray(frame).save(path)
            return
        except ImportError:
            pass

        try:
            import imageio.v3 as iio

            iio.imwrite(path, frame)
            return
        except ImportError as exc:
            raise RuntimeError(
                "Saving image files requires pillow or imageio. Use a .npy output_path instead."
            ) from exc
