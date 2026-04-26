# TASK

```json
{
  "status": "active",
  "task_id": "pharmacy_mvp_wave_001",
  "user_request": {
    "text": "Greet the customer, verify their mock ID, and have the arm wave when verification succeeds."
  },
  "goal": "Demonstrate a safe customer-facing pharmacy workflow where identity verification gates physical robot behavior.",
  "requested_patient": {
    "patient_id": "P-1042",
    "display_name": "Alex C."
  },
  "required_check": {
    "identity_verified": true,
    "minimum_age": 18
  },
  "success_behavior": {
    "reachy_frontdesk": "announce verification success",
    "so101_counter_arm": "wave"
  },
  "safety": {
    "real_medication": false,
    "direct_patient_handoff_allowed": false,
    "arm_motion_requires_identity_verification": true
  }
}
```
