# Robot Embodiment Declaration - Reachy Mini

This profile describes a Reachy Mini controlled through the official `reachy_mini`
Python SDK. The SDK talks to a Reachy Mini daemon over WebSocket/FastAPI.

## Identity

- **Name**: Reachy Mini
- **Type**: Desktop expressive robot with 6-DOF head, rotating body, two antennas, camera, speaker, microphones, and optional IMU
- **Runtime Topology**: PhyAgentOS HAL -> `reachy_mini` SDK client -> Reachy Mini daemon -> hardware or simulation backend

## Supported Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `connect_robot` | `robot_id` optional | Connect to the daemon and cache initial state |
| `check_connection` | `robot_id` optional | Verify daemon connection and refresh runtime state |
| `disconnect_robot` | `robot_id` optional | Disconnect SDK client |
| `get_state` | `robot_id` optional | Refresh joint, pose, daemon, and IMU state into `ENVIRONMENT.md` |
| `wake_up` | `robot_id` optional | Enable motors, then run SDK wake-up behavior |
| `goto_sleep` | `robot_id` optional | Run SDK sleep behavior |
| `goto_target` | `x`, `y`, `z`, `roll`, `pitch`, `yaw`, `antennas`, `body_yaw`, `duration_s`, `degrees`, `mm`, `method` | Smoothly move head, antennas, and/or body yaw |
| `set_target` | same pose fields as `goto_target` | Immediate target update for control loops |
| `set_head_pose` | pose fields or `head_pose_matrix` | Set only the head pose |
| `set_antennas` | preferred: `left`, `right`; legacy: `antennas: [right, left]`; `degrees`, `duration_s`, `smooth` | Move antenna joints |
| `set_body_yaw` | `body_yaw`, `degrees`, `duration_s`, `smooth` | Rotate body yaw |
| `look_at_world` | `x`, `y`, `z`, `duration_s` | Point the head toward a 3D location in the robot/world frame |
| `look_at_image` | `u`, `v`, `duration_s` | Point the head toward an image pixel using camera calibration |
| `play_sound` | `file` or `sound` | Play a sound through the SDK media manager |
| `capture_frame` | `output_path` ending in `.npy`, `.png`, `.jpg`, or `.jpeg` | Capture one camera frame and save it on the watchdog host |
| `play_recorded_move` | `library`, `name`, `initial_goto_duration` optional | Play a recorded Reachy Mini move from a Hugging Face dataset/library |
| `enable_motors` / `disable_motors` | `ids` optional | Enable or disable all motors, or named motors |
| `enable_gravity_compensation` / `disable_gravity_compensation` | none | Toggle head gravity compensation |
| `set_automatic_body_yaw` | `enabled` | Toggle SDK automatic body yaw |

## Action Examples

Prefer side-named antenna targets so the LLM does not need to remember the SDK
wire order:

```json
{
  "action_type": "set_antennas",
  "parameters": {
    "robot_id": "reachy_mini_001",
    "left": 20,
    "right": -20,
    "degrees": true,
    "duration_s": 0.5
  }
}
```

Capture a camera frame for later perception:

```json
{
  "action_type": "capture_frame",
  "parameters": {
    "robot_id": "reachy_mini_001",
    "output_path": "/tmp/reachy_mini_001_frame.npy"
  }
}
```

## Driver Configuration

Preferred `--driver-config` keys:

```json
{
  "robot_id": "reachy_mini_001",
  "host": "reachy-mini.local",
  "port": 8000,
  "connection_mode": "auto",
  "spawn_daemon": false,
  "use_sim": false,
  "timeout": 5.0,
  "media_backend": "no_media",
  "automatic_body_yaw": true,
  "reconnect_policy": "manual"
}
```

Use `connection_mode: "localhost_only"` for Reachy Mini Lite or local simulation.
Use `connection_mode: "network"` with `host` for a wireless robot.
Use `spawn_daemon: true` and `use_sim: true` only when the Python environment can
start the Reachy Mini daemon/simulation stack.

## SDK Notes

- The official package is `reachy-mini` / import module `reachy_mini`.
- It requires Python >=3.10.
- `ReachyMini()` connects to a daemon; the daemon must be running before normal
  hardware control works.
- `goto_target()` is preferred for gestures lasting at least about 0.5 seconds.
- `set_target()` is for high-rate control loops and can fight with a running
  daemon-side move if abused.

## Runtime Protocol

- **Connection channel**: `robots.<robot_id>.connection_state`
- **Pose channel**: `robots.<robot_id>.robot_pose.head_pose_matrix`
- **Joint channel**: `robots.<robot_id>.joint_state`
- **Daemon channel**: `robots.<robot_id>.daemon_status`
- **IMU channel**: `robots.<robot_id>.imu` when the daemon reports IMU data
