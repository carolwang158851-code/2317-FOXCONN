"""Governed, deterministic Official IR evidence ingestion for P1008.

The adapter is intentionally separate from the observation-only news crawler.
It accepts no caller-supplied URLs, performs no interpretation, and emits only
hash-bound official evidence for the existing ResearchContentOrchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
from typing import Any, Callable, Mapping
from urllib.parse import quote, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from ..contract_loader import ContractLoader
from ..governance import GovernanceBoundary, GovernanceError
from ..phaseb1_common import PhaseB1BoundaryError, atomic_write


AUTHORIZATION_REL = Path("contracts/p1008_report_governance/v1.0/authorizations/P1008_OFFICIAL_IR_EVIDENCE_INGESTION_AUTHORIZATION_V1.json")
REPORT_MANIFEST_REL = Path("contracts/p1008_report_governance/v1.0/contract.manifest.json")
RUNTIME_REL = Path("runtime/official_ir_evidence")
AUTHORIZATION_ID = "P1008_OFFICIAL_IR_EVIDENCE_INGESTION_AUTHORIZATION_V1"
QUARTERS = {"一": 1, "二": 2, "三": 3, "四": 4}


class OfficialIREvidenceError(RuntimeError):
    """The official-source boundary or evidence lineage could not be proven."""


@dataclass(frozen=True)
class FetchResponse:
    body: bytes
    final_url: str
    status: int = 200
    content_type: str = "text/html; charset=utf-8"
    headers: Mapping[str, str] | None = None


Transport = Callable[[str], FetchResponse]


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


class _SafeRedirect(HTTPRedirectHandler):
    def __init__(self, validate: Callable[[str], str]) -> None:
        super().__init__()
        self.validate = validate

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        self.validate(newurl)
        return super().redirect_request(req, fp, code, msg, headers, _ascii_transport_url(newurl))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _ascii_transport_url(url: str) -> str:
    """Encode only non-ASCII URL components for the HTTP transport layer."""
    parsed = urlsplit(url)
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        quote(parsed.path, safe="/%:@-._~!$&'()*+,;="),
        quote(parsed.query, safe="=&%:@/?-._~!$'()*+,;"),
        "",
    ))


def load_authorization(package_root: Path) -> dict[str, Any]:
    root = package_root.resolve()
    path = root / AUTHORIZATION_REL
    manifest_path = root / REPORT_MANIFEST_REL
    try:
        authorization = json.loads(path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OfficialIREvidenceError("AUTHORIZATION_UNAVAILABLE") from exc
    rel = AUTHORIZATION_REL.relative_to("contracts/p1008_report_governance/v1.0").as_posix()
    entry = next((item for item in manifest.get("artifacts", []) if item.get("path") == rel), None)
    if not entry or entry.get("sha256") != _sha256(path.read_bytes()) or entry.get("sizeBytes") != path.stat().st_size:
        raise OfficialIREvidenceError("AUTHORIZATION_NOT_MANIFEST_BOUND")
    if authorization.get("authorizationIdentity") != AUTHORIZATION_ID or authorization.get("ownerDecision") != "APPROVED":
        raise OfficialIREvidenceError("AUTHORIZATION_INVALID")
    if authorization.get("actionable") is not False or authorization.get("formalAuthorityWrites") != 0:
        raise OfficialIREvidenceError("AUTHORIZATION_BOUNDARY_INVALID")
    return authorization


def _period(text: str) -> tuple[int, int] | None:
    normalized = text.replace("２", "2").replace("１", "1").replace("３", "3").replace("４", "4")
    patterns = [
        re.search(r"(?i)([1-4])\s*Q\s*(20\d{2}|\d{2})", normalized),
        re.search(r"(?i)(20\d{2}|\d{2})\s*Q\s*([1-4])", normalized),
        re.search(r"(20\d{2})\s*年[^\n]{0,20}?第\s*([一二三四1-4])\s*季", normalized),
    ]
    if patterns[0]:
        quarter, year = int(patterns[0].group(1)), int(patterns[0].group(2))
    elif patterns[1]:
        year, quarter = int(patterns[1].group(1)), int(patterns[1].group(2))
    elif patterns[2]:
        year = int(patterns[2].group(1)); raw = patterns[2].group(2); quarter = QUARTERS.get(raw, int(raw) if raw.isdigit() else 0)
    else:
        return None
    return (2000 + year if year < 100 else year, quarter)


def _identity(period: tuple[int, int]) -> tuple[str, str]:
    year, quarter = period
    return f"HON_HAI_FY{year}_Q{quarter}_EARNINGS", f"P1008_FY{year}_Q{quarter}_EARNINGS"


def _event_period(canonical_event_id: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"HON_HAI_FY(20\d{2})_Q([1-4])_EARNINGS", canonical_event_id)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _source_failure_status(error: str) -> str:
    if "TIMEOUT" in error:
        return "TIMEOUT"
    if error.startswith("HTTP_") or error in {"OFFICIAL_ENDPOINT_ERROR", "NETWORK_FETCH_FAILED:HTTPError"}:
        return "HTTP_ERROR"
    if error in {"OFF_DOMAIN_URL_REJECTED", "PRIVATE_NETWORK_REJECTED", "URL_POLICY_REJECTED"}:
        return "SECURITY_REJECTED"
    if error in {"PDF_CONTENT_MISMATCH", "HTML_CONTENT_TYPE_REQUIRED", "TRANSPORT_RESPONSE_INVALID", "RESPONSE_TOO_LARGE"}:
        return "VALIDATION_FAILED"
    return "HTTP_ERROR"


class OfficialIREvidenceAdapter:
    def __init__(self, package_root: Path | str, *, transport: Transport | None = None) -> None:
        self.package_root = Path(package_root).resolve()
        self.filesystem_governance = GovernanceBoundary(
            ContractLoader(self.package_root)
        )
        self.authorization = load_authorization(self.package_root)
        self.transport = transport
        self.origins = self.authorization["allowedOrigins"]
        self.fixed_sources = {item["url"]: item for item in self.authorization["sources"]}

    def validate_url(self, url: str, *, fixed_page: bool = False) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise OfficialIREvidenceError("URL_POLICY_REJECTED")
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"}:
            raise OfficialIREvidenceError("PRIVATE_NETWORK_REJECTED")
        allowed = any(host == item["host"] and any(parsed.path.startswith(prefix) for prefix in item["pathPrefixes"]) for item in self.origins)
        if not allowed or (fixed_page and url not in self.fixed_sources):
            raise OfficialIREvidenceError("OFF_DOMAIN_URL_REJECTED")
        try:
            literal = ipaddress.ip_address(host)
            if not literal.is_global:
                raise OfficialIREvidenceError("PRIVATE_NETWORK_REJECTED")
        except ValueError:
            pass
        return url

    def _validate_live_url(self, url: str) -> str:
        self.validate_url(url)
        host = urlparse(url).hostname or ""
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise OfficialIREvidenceError("NETWORK_RESOLUTION_FAILED") from exc
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise OfficialIREvidenceError("PRIVATE_NETWORK_REJECTED")
        return url

    def _fetch_live(self, url: str) -> FetchResponse:
        self._validate_live_url(url)
        opener = build_opener(_SafeRedirect(self._validate_live_url))
        transport_url = _ascii_transport_url(url)
        self._validate_live_url(transport_url)
        request = Request(transport_url, headers={"User-Agent": "P1008-Official-IR-Evidence/1.0", "Accept": "text/html,application/pdf"})
        try:
            with opener.open(request, timeout=int(self.authorization["timeoutSeconds"])) as response:
                maximum = int(self.authorization["maxResponseBytes"])
                body = response.read(maximum + 1)
                if len(body) > maximum:
                    raise OfficialIREvidenceError("RESPONSE_TOO_LARGE")
                return FetchResponse(body, response.geturl(), int(response.status), response.headers.get("Content-Type", ""), dict(response.headers.items()))
        except OfficialIREvidenceError:
            raise
        except Exception as exc:
            raise OfficialIREvidenceError(f"NETWORK_FETCH_FAILED:{type(exc).__name__}") from exc

    def _fetch(self, url: str, *, fixed_page: bool = False) -> FetchResponse:
        self.validate_url(url, fixed_page=fixed_page)
        response = self.transport(url) if self.transport else self._fetch_live(url)
        if not isinstance(response, FetchResponse):
            raise OfficialIREvidenceError("TRANSPORT_RESPONSE_INVALID")
        self.validate_url(response.final_url)
        if len(response.body) > int(self.authorization["maxResponseBytes"]):
            raise OfficialIREvidenceError("RESPONSE_TOO_LARGE")
        if urlparse(response.final_url).path.startswith("/mops/error/"):
            raise OfficialIREvidenceError("OFFICIAL_ENDPOINT_ERROR")
        if response.status != 200:
            raise OfficialIREvidenceError(f"HTTP_{response.status}")
        return response

    @staticmethod
    def _links(response: FetchResponse) -> tuple[str, list[tuple[str, str]]]:
        if "html" not in response.content_type.lower():
            raise OfficialIREvidenceError("HTML_CONTENT_TYPE_REQUIRED")
        text = response.body.decode("utf-8", errors="replace")
        parser = _Links(); parser.feed(text)
        return text, [(urljoin(response.final_url, href), label) for href, label in parser.links]

    def _receipt(self, *, source: Mapping[str, Any], response: FetchResponse, document_type: str, period: tuple[int, int] | None, run_dir: Path) -> dict[str, Any]:
        raw_hash = _sha256(response.body)
        payload = {
            "recordType": "P1008_OFFICIAL_IR_RAW_RECEIPT_V1", "authorizationIdentity": AUTHORIZATION_ID,
            "source_id": source["sourceId"], "source_type": "OFFICIAL_WEB" if source["role"] != "MOPS_OFFICIAL_DISCLOSURE" else "REGULATORY_FILING",
            "source_class": "AUTHORITY", "source_tier": "OFFICIAL", "source_locator": response.final_url,
            "source_url": source["url"], "final_url": response.final_url, "retrieved_at_utc": self.retrieved_at,
            "http_status": response.status, "content_type": response.content_type, "content_length": len(response.body),
            "raw_sha256": raw_hash, "source_hash": raw_hash,
            "originating_chain_id": f"OFFICIAL-IR-{source['sourceId']}", "document_type": document_type,
            "fiscal_period": f"FY{period[0]} Q{period[1]}" if period else None, "actionable": False,
        }
        receipt_id = "IR-RECEIPT-" + _sha256(_canonical(payload))[:20]
        receipt = {**payload, "receipt_id": receipt_id}
        path = run_dir / "receipts" / f"{receipt_id}.json"
        self._authorize_output(path)
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != receipt:
                raise OfficialIREvidenceError("RECEIPT_COLLISION")
        else:
            atomic_write(path, _canonical(receipt), capability="OFFICIAL_IR_EVIDENCE")
        raw_path = run_dir / "raw" / f"{receipt_id}.bin"
        self._authorize_output(raw_path)
        if raw_path.exists() and _sha256(raw_path.read_bytes()) != raw_hash:
            raise OfficialIREvidenceError("RAW_CACHE_HASH_MISMATCH")
        if not raw_path.exists():
            atomic_write(
                raw_path, response.body, capability="OFFICIAL_IR_EVIDENCE"
            )
        receipt["receipt_path"] = path.relative_to(self.package_root).as_posix()
        receipt["raw_artifact_path"] = raw_path.relative_to(self.package_root).as_posix()
        return receipt

    def _authorize_output(self, target: Path) -> Path:
        try:
            return self.filesystem_governance.authorize_write(
                "OFFICIAL_IR_EVIDENCE", target
            )
        except GovernanceError as exc:
            raise OfficialIREvidenceError(
                f"FILESYSTEM_AUTHORIZATION_DENIED:{exc}"
            ) from exc

    def _evidence(self, receipt: Mapping[str, Any], period: tuple[int, int], document_type: str) -> dict[str, Any]:
        canonical_id, _ = _identity(period)
        source_type = "REGULATORY_FILING" if receipt["source_id"] == "MOPS_OFFICIAL_DISCLOSURE" else ("COMPANY_FILING" if document_type == "QUARTERLY_REPORT_CONFIRMED" else "OFFICIAL_WEB")
        event_id = "IR-EVIDENCE-" + _sha256(_canonical({"canonical": canonical_id, "source": receipt["source_id"], "hash": receipt["source_hash"]}))[:20]
        return {
            "event_id": event_id, "event_type": "QUARTERLY_EARNINGS", "event_status": "MATERIAL_EVENT_CONFIRMED",
            "occurred_at_utc": self.event_time, "published_at_utc": self.retrieved_at, "received_at_utc": self.retrieved_at,
            "data_cutoff": self.retrieved_at[:10], "source_id": receipt["source_id"], "source_type": source_type,
            "source_class": "AUTHORITY", "source_locator": receipt["receipt_path"], "source_url": receipt["final_url"],
            "source_tier": "OFFICIAL", "source_hash": receipt["source_hash"], "originating_chain_id": receipt["originating_chain_id"],
            "evidence_ids": [event_id], "claim_summary": f"Hon Hai published FY{period[0]} Q{period[1]} financial results.",
            "affected_kpis": [], "materiality": "MATERIAL_RESULTS_PUBLICATION", "novelty": "NEW_OFFICIAL_DOCUMENT",
            "evidence_status": "CONFIRMED", "validation_status": "OFFICIAL_VERIFIED", "confidence": 1.0,
            "quality_metadata": {"document_type": document_type, "raw_byte_hash_bound": True},
            "provenance": {key: receipt[key] for key in ("receipt_id", "receipt_path", "raw_artifact_path", "final_url", "retrieved_at_utc", "http_status", "content_type", "content_length", "raw_sha256", "authorizationIdentity")},
            "canonical_event_id": canonical_id, "verification_status": "OFFICIAL_VERIFIED", "counter_evidence_ids": [],
            "missing_evidence": [], "source_conflicts": [], "actionable": False,
        }

    @staticmethod
    def _document_type(role: str, label: str, url: str, page_text: str) -> tuple[str, tuple[int, int]] | None:
        link_material = " ".join((label, url.rsplit("/", 1)[-1]))
        material = link_material if role in {"HON_HAI_INVESTOR_CONFERENCE", "HON_HAI_QUARTERLY_REPORTS"} else " ".join((link_material, page_text[:300]))
        period = _period(material)
        if not period:
            return None
        lowered = material.lower()
        if role == "HON_HAI_INVESTOR_CONFERENCE" and "transcript" in lowered:
            return "CALL_TRANSCRIPT_CONFIRMED", period
        if role == "HON_HAI_INVESTOR_CONFERENCE" and ("result" in lowered or "業績" in material or "財務結果" in material):
            return "RESULTS_DOCUMENT_CONFIRMED", period
        if role == "HON_HAI_QUARTERLY_REPORTS" and (".pdf" in lowered or "財務報" in material):
            return "QUARTERLY_REPORT_CONFIRMED", period
        if role == "HON_HAI_PRESS_RELEASES" and any(term in material for term in ("財務結果", "財報", "營運成果")) and any(term in material for term in ("季", "Q")):
            return "RESULTS_PRESS_RELEASE_CONFIRMED", period
        if role == "MOPS_OFFICIAL_DISCLOSURE" and "2317" in page_text and any(term in page_text for term in ("財務報告", "財務報表", "第二季", "Q2")):
            return "MOPS_RESULTS_DISCLOSURE_CONFIRMED", period
        return None

    def scan(self, *, target_period: tuple[int, int] | None = None, evaluated_at_utc: str | None = None) -> dict[str, Any]:
        self.retrieved_at = evaluated_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.event_time = self.retrieved_at
        run_id = "P1008-OFFICIAL-IR-" + self.retrieved_at.replace("-", "").replace(":", "").replace(".", "").replace("+00:00", "Z")
        run_dir = self._authorize_output(self.package_root / RUNTIME_REL / run_id)
        evidence: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        source_statuses: list[dict[str, Any]] = []
        schedule: dict[str, Any] | None = None
        seen_documents: set[tuple[str, str]] = set()
        for source in self.authorization["sources"][: int(self.authorization["maxPages"])]:
            source_evidence: list[dict[str, Any]] = []
            receipt_count_before = len(receipts)
            try:
                page = self._fetch(source["url"], fixed_page=True)
                text, links = self._links(page)
                page_receipt = self._receipt(source=source, response=page, document_type="SOURCE_PAGE", period=None, run_dir=run_dir)
                receipts.append(page_receipt)
                if source["role"] == "HON_HAI_EVENT_CALENDAR":
                    periods = [(value, match.group(0)) for match in re.finditer(r"20\d{2}[^\n<]{0,30}?(?:第[一二三四1-4]季|[1-4]Q|Q[1-4])[^\n<]{0,20}?(?:法人說明會|earnings|conference)", text, re.I) if (value := _period(match.group(0)))]
                    eligible_periods = [item for item in periods if target_period is None or item[0] == target_period]
                    selected = max(eligible_periods, key=lambda item: item[0], default=None)
                    if selected:
                        canonical_id, report_key = _identity(selected[0]); schedule = {"state": "EVENT_SCHEDULE_CONFIRMED", "event": canonical_id, "report_key": report_key, "fiscal_period": f"FY{selected[0][0]} Q{selected[0][1]}", "title": selected[1], "source_id": source["sourceId"], "receipt_id": page_receipt["receipt_id"], "actionable": False}
                    source_statuses.append({"source_id": source["sourceId"], "status": "SUCCESS" if selected else "NO_CHANGE", "evidence_count": 0, "receipt_count": len(receipts) - receipt_count_before})
                    continue
                candidates = list(links)
                if source["role"] == "MOPS_OFFICIAL_DISCLOSURE":
                    candidates.append((page.final_url, text))
                for document_url, label in candidates:
                    classified = self._document_type(source["role"], label, document_url, text)
                    if not classified:
                        continue
                    document_type, period = classified
                    key = (document_url, document_type)
                    if key in seen_documents or len(seen_documents) >= int(self.authorization["maxDocuments"]):
                        continue
                    seen_documents.add(key)
                    response = page if document_url == page.final_url else self._fetch(document_url)
                    if document_url.lower().split("?", 1)[0].endswith(".pdf"):
                        if "pdf" not in response.content_type.lower() or not response.body.startswith(b"%PDF-"):
                            raise OfficialIREvidenceError("PDF_CONTENT_MISMATCH")
                    receipt = self._receipt(source=source, response=response, document_type=document_type, period=period, run_dir=run_dir)
                    receipts.append(receipt)
                    source_evidence.append(self._evidence(receipt, period, document_type))
                evidence.extend(source_evidence)
                source_statuses.append({"source_id": source["sourceId"], "status": "SUCCESS" if source_evidence else "NOT_YET_AVAILABLE", "evidence_count": len(source_evidence), "receipt_count": len(receipts) - receipt_count_before})
            except OfficialIREvidenceError as exc:
                error = str(exc)
                failure_status = _source_failure_status(error)
                failure = {"source_id": source["sourceId"], "status": failure_status, "error": error}
                failures.append(failure)
                source_statuses.append({**failure, "evidence_count": 0, "receipt_count": len(receipts) - receipt_count_before})
        deduped = {(item["canonical_event_id"], item["source_id"], item["source_hash"]): item for item in evidence}
        detected_evidence = sorted(
            deduped.values(),
            key=lambda item: (item["canonical_event_id"], item["source_id"], item["source_hash"]),
        )
        detected_periods = {
            period
            for item in detected_evidence
            if (period := _event_period(item["canonical_event_id"])) is not None
        }
        schedule_period = _period(schedule["fiscal_period"]) if schedule else None
        if target_period is not None:
            selected_period = target_period
        elif detected_periods:
            selected_period = schedule_period if schedule_period in detected_periods else max(detected_periods)
        else:
            selected_period = schedule_period
        canonical_id, report_key = _identity(selected_period) if selected_period else ("", f"P1008_DAILY_{self.retrieved_at[:10].replace('-', '')}")
        active_event_evidence = [
            item for item in detected_evidence if item["canonical_event_id"] == canonical_id
        ]
        historical_evidence = [
            item for item in detected_evidence if item["canonical_event_id"] != canonical_id
        ]
        active_ids = {item["canonical_event_id"] for item in active_event_evidence}
        if active_ids and active_ids != {canonical_id}:
            raise OfficialIREvidenceError("OFFICIAL_IR_CANONICAL_EVENT_SCOPE_MISMATCH")
        if selected_period and report_key != _identity(selected_period)[1]:
            raise OfficialIREvidenceError("OFFICIAL_IR_CANONICAL_EVENT_SCOPE_MISMATCH")
        coverage_complete = not failures
        successful_sources = [item["source_id"] for item in source_statuses if item["status"] in {"SUCCESS", "NO_CHANGE", "NOT_YET_AVAILABLE"}]
        if failures:
            status = "PARTIAL_FAILURE_WITH_AUTHORITY" if active_event_evidence else ("PARTIAL_FAILURE_NO_AUTHORITY" if successful_sources else "FAIL_CLOSED")
            scan_status = "PARTIAL_FAILURE" if successful_sources else "FAIL_CLOSED"
        else:
            status = "AUTHORITY_EVIDENCE_READY" if active_event_evidence else ("SCHEDULE_CONFIRMED" if schedule else "NO_CHANGE")
            scan_status = "COMPLETE"
        result = {
            "record_type": "P1008_OFFICIAL_IR_EVIDENCE_SCAN_V1", "run_id": run_id,
            "status": status, "scan_status": scan_status, "scan_integrity_valid": True,
            "coverage_complete": coverage_complete, "source_scan_complete": coverage_complete,
            "successful_sources": successful_sources, "failed_sources": failures, "source_statuses": source_statuses,
            "authorization_identity": AUTHORIZATION_ID, "evaluated_at_utc": self.retrieved_at,
            "canonical_event_id": canonical_id, "report_key": report_key, "revision": 1,
            "active_fiscal_period": f"FY{selected_period[0]} Q{selected_period[1]}" if selected_period else "",
            "schedule": schedule,
            "detected_evidence": detected_evidence,
            "active_event_evidence": active_event_evidence,
            "historical_evidence": historical_evidence,
            "validated_event_evidence": active_event_evidence,
            "detected_evidence_count": len(detected_evidence),
            "active_event_evidence_count": len(active_event_evidence),
            "historical_evidence_count": len(historical_evidence),
            "receipt_paths": [item["receipt_path"] for item in receipts], "failures": failures,
            "analysis_generated": False, "report_generated": False, "publication_count": 0, "actionable": False,
        }
        try:
            atomic_write(
                run_dir / "scan_result.json",
                _canonical(result),
                overwrite=True,
                capability="OFFICIAL_IR_EVIDENCE",
            )
            latest = self._authorize_output(
                self.package_root / RUNTIME_REL / "latest_status.json"
            )
            atomic_write(
                latest,
                _canonical(result),
                overwrite=True,
                capability="OFFICIAL_IR_EVIDENCE",
            )
        except PhaseB1BoundaryError as exc:
            raise OfficialIREvidenceError(
                f"FILESYSTEM_AUTHORIZATION_DENIED:{exc}"
            ) from exc
        return result
