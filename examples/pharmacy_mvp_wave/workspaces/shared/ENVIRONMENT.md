# ENVIRONMENT

```json
{
  "schema_version": "PhyAgentOS.environment.v1",
  "updated_at": "2026-04-26T00:00:00Z",
  "objects": {
    "pharmacy_demo": {
      "workspace_clear": true,
      "human_hand_in_workspace": false,
      "customer": {
        "present": true,
        "identity_status": "unverified"
      }
    },
    "reachy_frontdesk": {
      "status": "idle",
      "last_action": null,
      "last_spoken_text": null
    },
    "identity_checker": {
      "status": "ready",
      "last_result": null
    },
    "so101_counter_arm": {
      "type": "tabletop_gesture_arm",
      "status": "home",
      "last_action": null,
      "emergency_stop": false,
      "wave_completed": false
    }
  },
  "robots": {
    "reachy_frontdesk": {
      "type": "reachy_mini",
      "connection_state": {
        "status": "unknown"
      }
    },
    "so101_counter_arm": {
      "type": "so101_greeting_arm",
      "connection_state": {
        "status": "unknown"
      },
      "gesture_state": {
        "status": "home",
        "wave_completed": false,
        "emergency_stop": false
      }
    }
  },
  "scene_graph": {
    "nodes": [],
    "edges": []
  }
}
```
