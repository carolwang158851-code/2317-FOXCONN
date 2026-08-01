"""Loopback-only test server for the frozen status route."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Type

from .service import StatusService


class StatusServerError(RuntimeError):
    """Raised when the isolated status server boundary is violated."""


def _handler_type(service: StatusService) -> Type[BaseHTTPRequestHandler]:
    class StatusHandler(BaseHTTPRequestHandler):
        server_version = "P1008ResearchSkeleton/0.1"

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            if self.path != "/api/research-plugin/status":
                self._send_json(404, {"error": "NOT_FOUND", "actionable": False})
                return
            try:
                payload = service.build_status()
            except Exception:
                try:
                    payload = service.unavailable_status()
                except Exception:
                    payload = {
                        "contract_version": "1.0",
                        "implementation_status": "SKELETON",
                        "runtime_status": "UNAVAILABLE",
                        "last_successful_run": None,
                        "data_freshness": "UNKNOWN",
                        "rqs": None,
                        "rhs": None,
                        "evidence_gate_result": "NOT_EVALUATED",
                        "legacy_reuse_violation_count": 0,
                        "owner_review_count": 0,
                        "open_gap_count": 0,
                        "overdue_debt_count": 0,
                        "openai_enabled": False,
                        "actionable": False,
                    }
                self._send_json(503, payload)
                return
            self._send_json(200, payload)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            self._send_json(
                405,
                {
                    "error": "PHASE_1B_STATUS_IS_READ_ONLY",
                    "actionable": False,
                },
            )

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return StatusHandler


def make_status_server(
    service: StatusService, host: str = "127.0.0.1", port: int = 0
) -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise StatusServerError("Phase 1B status server must bind to 127.0.0.1")
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise StatusServerError("Invalid status server port")
    return ThreadingHTTPServer((host, port), _handler_type(service))
