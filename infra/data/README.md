# Data Foundation

`infra/data` is the new data foundation for the AITC refactor. It is designed
to be introduced gradually while existing modules remain in place.

Current scope:

- Receive and persist traffic sensing records.
- Keep recent per-intersection traffic windows in memory.
- Persist configuration items.
- Persist experience-pool items.
- Provide a small Python API for Agent and legacy code.

Runtime data is written under `infra/data/runtime/` by default and should not be
committed.
