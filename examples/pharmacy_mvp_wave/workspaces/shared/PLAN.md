# PLAN

Task: Greet customer, verify mock identity, and trigger SO-101 wave.

1. Reachy greets the customer.
2. Reachy asks the customer to show a mock ID.
3. Identity checker verifies patient ID `P-1042` and age >= 18.
4. If identity verification fails:
   - Reachy announces failure.
   - SO-101 does not move.
5. If identity verification passes:
   - Reachy announces verification success.
   - SO-101 performs a friendly wave.
6. Reachy announces that the verified demo workflow is complete.
