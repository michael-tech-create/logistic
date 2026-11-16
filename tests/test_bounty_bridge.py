import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import api.main as api
import bounty_bridge as bridge


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {"BOUNTY_BRIDGE_DB": str(Path(self.tmp.name) / "bridge.sqlite"), "BOUNTY_COMPANY_ID": "owner", "QUOTE_INTERNAL_TOKEN": "fixture"})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(api.app)
        self.headers = {"X-API-Key": "fixture"}
        self.record = {"record_id": "desk-fixture", "company_id": "owner", "source_text": "PRIVATE CUSTOMER DATA"}
        loader = patch.object(bridge, "load_quote", side_effect=lambda *_: self.record.copy())
        loader.start()
        self.addCleanup(loader.stop)

    def decision(self, ref, status="approved", headers=None):
        return self.client.post(f"/api/v1/quote-events/{ref}/decision", headers=self.headers if headers is None else headers, json={"status": status})

    def test_real_extract_schema_auth_and_durable_idempotency(self):
        body = {"text": "Ocean freight quote\nOrigin: Lagos\nDestination: Houston\nCharges:\n- Freight: USD 1800\nTotal Amount Due: USD 1800", "idempotency_key": "fixture"}
        self.assertEqual(self.client.post("/api/v1/extract", json=body).status_code, 401)
        first = self.client.post("/api/v1/extract", headers=self.headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["financials"]["total_amount"], 1800)
        self.assertIn("transport_mode", first.json()["shipment_details"])
        with patch.object(api, "parse_freight_quote", side_effect=AssertionError("cached across new connections")):
            retry = self.client.post("/api/v1/extract", headers=self.headers, json=body)
        self.assertEqual(retry.json(), first.json())
        body["text"] += " changed"
        self.assertEqual(self.client.post("/api/v1/extract", headers=self.headers, json=body).status_code, 409)

    def test_decision_persists_replays_and_conflicts(self):
        ref = bridge.enqueue(self.record)
        self.assertEqual(bridge.enqueue(self.record), ref)
        self.assertEqual(self.decision(ref, headers={}).status_code, 401)
        with ThreadPoolExecutor(max_workers=4) as workers:
            statuses = list(workers.map(lambda _: self.decision(ref).status_code, range(4)))
        self.assertEqual(statuses, [200]*4)
        self.assertEqual(self.decision(ref, "rejected").status_code, 409)
        response = self.client.get(f"/api/v1/quote-events/{ref}", headers=self.headers)
        self.assertEqual(response.json()["status"], "approved")
        self.assertTrue(response.json()["decided_at"])
        self.assertNotIn("PRIVATE", response.text)

    def test_stale_foreign_and_unknown_events(self):
        self.assertIsNone(bridge.enqueue({**self.record, "company_id": "foreign"}))
        ref = bridge.enqueue(self.record)
        self.record["source_text"] = "changed"
        self.assertEqual(self.decision(ref).status_code, 409)
        newer = bridge.enqueue(self.record)
        self.assertNotEqual(newer, ref)
        self.assertEqual(self.decision(ref).status_code, 409)
        self.assertEqual(self.decision(newer, "rejected").status_code, 200)
        with patch.dict(os.environ, {"BOUNTY_COMPANY_ID": "foreign"}):
            self.assertEqual(self.decision(newer, "rejected").status_code, 404)
        self.assertEqual(self.decision("0"*32).status_code, 404)

    def test_outbox_retries_metadata_only(self):
        ref = bridge.enqueue(self.record)
        seen = []
        def send(kind, event):
            seen.append((kind, event))
            return len(seen) > 1
        bridge.deliver_pending(send)
        bridge.deliver_pending(send)
        bridge.deliver_pending(send)
        self.assertEqual(seen, [("quote_ready", ref)]*2)

    @unittest.skipUnless(os.environ.get("BOUNTY_AGENT_REPO"), "requires Go bounty checkout")
    def test_go_client_against_real_api(self):
        import socket
        import subprocess
        import threading
        import uvicorn
        ref = bridge.enqueue(self.record)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(api.app, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            import time
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            self.assertTrue(server.started)
            env = {**os.environ, "BOUNTY_LOGISTICS_CONTRACT_URL": f"http://127.0.0.1:{sock.getsockname()[1]}", "BOUNTY_LOGISTICS_CONTRACT_REF": ref, "GOCACHE": "/tmp/bounty-go-cache"}
            result = subprocess.run([os.environ.get("GO_BINARY", "go"), "test", "./internal/quoteclient", "-run", "^TestLogisticsServiceContract$", "-count=1"], cwd=os.environ["BOUNTY_AGENT_REPO"], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            sock.close()

    def test_save_quote_enqueues_after_persistence(self):
        with patch("desk_ops.save_record") as save, patch.object(api, "ensure_company", return_value={"code": "owner"}):
            api._save_desk_quote(self.record.copy(), {"id": 1})
        save.assert_called_once()
        with bridge.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 1)

if __name__ == "__main__":
    unittest.main()
