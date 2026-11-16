# Bounty integration

See the [integration guide](../../light-bouty/bounty-agent/docs/logistics-integration.md)
and [shared OpenAPI contract](../../light-bouty/bounty-agent/docs/contracts/logistics.openapi.yaml).

Set `BOUNTY_COMPANY_ID` to opt one company into quote notifications. API quote
saves enqueue metadata-only alerts. Run `.venv/bin/python notify_bounty.py`
periodically to drain the persistent outbox. Persist `BOUNTY_BRIDGE_DB`.

Quote review decisions are separate from payment and clearance approvals.
No incoming quote payload is sent to the bounty agent.

Run the local contract and regression tests:

```bash
.venv/bin/python -m unittest tests.test_bounty_bridge tests.test_workflow tests.test_approval_flow
```

For the actual Go-to-FastAPI contract check, set `BOUNTY_AGENT_REPO` to the Go
checkout and `GO_BINARY` to its Go executable before running the same command.
