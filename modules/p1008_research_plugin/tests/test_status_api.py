from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.adapters.authority_adapter import AuthorityAdapter
from p1008_research_plugin.adapters.runtime_snapshot_adapter import RuntimeSnapshotAdapter
from p1008_research_plugin.contract_loader import ContractLoader
from p1008_research_plugin.governance import GovernanceBoundary
from p1008_research_plugin.status.server import StatusServerError, make_status_server
from p1008_research_plugin.status.service import StatusService


class StatusApiTests(unittest.TestCase):
    def setUp(self) -> None:
        loader = ContractLoader(PACKAGE_ROOT)
        self.loader = loader
        self.service = StatusService(
            loader,
            GovernanceBoundary(loader),
            AuthorityAdapter(PACKAGE_ROOT, loader),
            RuntimeSnapshotAdapter(PACKAGE_ROOT),
        )

    def test_status_matches_frozen_schema_and_phase1b_boundary(self) -> None:
        status = self.service.build_status()
        expected = json.loads(
            (MODULE_ROOT / "tests" / "fixtures" / "status_expected.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status, expected)
        self.assertFalse(status["openai_enabled"])
        self.assertFalse(status["actionable"])

    def test_loopback_status_server_get_only(self) -> None:
        server = make_status_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        base = f"http://{host}:{port}"
        try:
            with urllib.request.urlopen(
                base + "/api/research-plugin/status", timeout=5
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["implementation_status"], "SKELETON")
            request = urllib.request.Request(
                base + "/api/research-plugin/status", method="POST", data=b"{}"
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(error.exception.code, 405)
            error.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + "/health", timeout=5)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_non_loopback_bind_is_rejected(self) -> None:
        with self.assertRaises(StatusServerError):
            make_status_server(self.service, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
