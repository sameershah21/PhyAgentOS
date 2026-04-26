# IDENTITY

```json
{
  "status": "not_checked",
  "patient_id": null,
  "name_match": null,
  "age_verified": null,
  "minimum_required_age": 18,
  "privacy": {
    "raw_id_image_stored": false
  }
}
```

## Verified Mock State

Use this state after the synthetic QR/profile check passes:

```json
{
  "status": "verified_mock",
  "patient_id": "P-1042",
  "name_match": true,
  "age_verified": true,
  "minimum_required_age": 18,
  "method": "mock_qr",
  "privacy": {
    "raw_id_image_stored": false,
    "retained_fields": [
      "patient_id",
      "name_match",
      "age_verified",
      "verification_status"
    ]
  }
}
```
