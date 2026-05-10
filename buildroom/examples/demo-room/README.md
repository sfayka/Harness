# Demo Room: Client HTML Delivery

This sanitized demo room models a Knox Auto-build v0 flow for client-facing HTML delivery.

It starts from evidence that BP Audit Studio needs a better client/prospect delivery mechanism and ends with a clean operator summary. It does **not** publish, deploy, mutate GitHub/Linear, or delete anything.

Run:

```bash
python3 scripts/validate_buildroom.py buildroom/examples/demo-room
```

Expected result: `valid: true`, trust state `clean`, retention recommendation `keep`.
