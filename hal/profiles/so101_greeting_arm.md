# SO-101 Greeting Arm

## Identity

- **Name**: SO-101 Greeting Arm
- **Robot ID**: `so101_counter_arm`
- **Type**: tabletop gesture arm
- **Driver**: `so101_greeting` / `so101`
- **MVP Role**: visible, non-contact acknowledgement gestures after mock identity verification

## Role

SO-101 performs simple visible gestures in the pharmacy demo. Its purpose in
this MVP is to show that physical robot behavior can be gated by PhyAgentOS
state files, especially `IDENTITY.md`.

SO-101 does not pick up objects in this MVP.

## Capabilities

- Can move to a home pose.
- Can perform a small wave gesture.
- Can perform an acknowledgement gesture.
- Can stop safely.
- Can update environment state after completing a gesture.

## Limitations

- Cannot pick objects.
- Cannot manipulate medication.
- Cannot open bottles.
- Cannot hand anything to a customer.
- Cannot move unless the workspace is clear.
- Cannot wave unless mock identity verification has passed.
- Cannot operate if emergency stop is active.

## Allowed Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `connect_robot` | `{}` | Mark the greeting-arm driver connected |
| `check_connection` | `{}` | Report connection health |
| `home` | `{}` | Return the arm to a neutral safe pose |
| `wave` | `style: small \| friendly \| celebratory`, `duration_sec` | Perform a visible success wave |
| `acknowledge` | `style: nod \| small_wave \| point_to_counter` | Perform a non-sensitive acknowledgement gesture |
| `stop` | `reason` | Cancel motion and enter a safe stopped state |

## Preconditions

### `home`

- `ENVIRONMENT.objects.so101_counter_arm.emergency_stop == false`

### `wave`

- `IDENTITY.status == verified_mock`
- `IDENTITY.age_verified == true`
- `ENVIRONMENT.objects.pharmacy_demo.workspace_clear == true`
- `ENVIRONMENT.objects.pharmacy_demo.human_hand_in_workspace == false`
- `ENVIRONMENT.objects.so101_counter_arm.emergency_stop == false`

### `acknowledge`

- `ENVIRONMENT.objects.pharmacy_demo.workspace_clear == true`
- `ENVIRONMENT.objects.so101_counter_arm.emergency_stop == false`

## Postconditions

After `wave` succeeds:

- `ENVIRONMENT.objects.so101_counter_arm.last_action.action_type == "wave"`
- `ENVIRONMENT.objects.so101_counter_arm.wave_completed == true`
- `ENVIRONMENT.robots.so101_counter_arm.gesture_state.status == "home"`

## Forbidden Actions

- `pick_from_slot`
- `place_in_tray`
- `dispense_medication`
- `hand_to_patient`
- `open_bottle`
- `count_pills`
- `touch_customer`
- `move_when_workspace_blocked`

## Safety Rules

1. The arm must not move if the workspace is blocked.
2. The `wave` action requires `IDENTITY.status == verified_mock`.
3. The arm must not move toward the customer.
4. The arm must not touch any objects in this MVP.
5. If identity verification fails, do not wave. Ask Reachy to explain the failure.

## Driver Configuration

```json
{
  "robot_id": "so101_counter_arm",
  "workspace": "/tmp/pharmacy_mvp_wave/workspaces/so101_counter_arm",
  "identity_path": "/tmp/pharmacy_mvp_wave/workspaces/shared/IDENTITY.md",
  "backend": "dry_run"
}
```

`backend: "dry_run"` validates the safety gates and writes state without
touching hardware. Replace `run_trajectory()` in the driver with calibrated
SO-101 joint control for the real arm.
