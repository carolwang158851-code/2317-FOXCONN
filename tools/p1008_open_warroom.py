#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fast local launcher for P1008 warroom app.

This checks ports briefly, starts a local UTF-8 app server if needed, and opens
the browser without long blocking waits.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


DEFAULT_PORT_START = 8767
DEFAULT_PORT_END = 8899
EXPECTED_SERVER_VERSION = "P1008_APP_SERVER_20260710_FULLSCREEN_REPORT_V1"


def browser_candidates() -> list[str]:
    candidates: list[str] = []
    for command in ("msedge", "chrome"):
        resolved = shutil.which(command)
        if resolved:
            candidates.append(resolved)
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")]
    known_paths = [
        Path(program_files[0]) / "Microsoft/Edge/Application/msedge.exe" if program_files[0] else None,
        Path(program_files[1]) / "Microsoft/Edge/Application/msedge.exe" if len(program_files) > 1 and program_files[1] else None,
        Path(local_app_data) / "Microsoft/Edge/Application/msedge.exe" if local_app_data else None,
        Path(program_files[0]) / "Google/Chrome/Application/chrome.exe" if program_files[0] else None,
        Path(program_files[1]) / "Google/Chrome/Application/chrome.exe" if len(program_files) > 1 and program_files[1] else None,
        Path(local_app_data) / "Google/Chrome/Application/chrome.exe" if local_app_data else None,
    ]
    for path in known_paths:
        if path and path.exists():
            candidates.append(str(path))
    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        key = str(Path(item)).lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def open_immersive_browser(url: str) -> bool:
    """Open Launcher in a browser-controlled app/fullscreen window when possible."""
    args = [
        "--new-window",
        "--start-fullscreen",
        f"--app={url}",
        "--no-first-run",
        "--disable-features=Translate",
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    for browser_exe in browser_candidates():
        try:
            subprocess.Popen(
                [browser_exe, *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
            print(f"[OK] Opened immersive browser: {browser_exe}")
            return True
        except OSError:
            continue
    return False


def news_health_is_blocked(payload: dict) -> bool:
    source_manifest = payload.get("sourceManifest", {}) if isinstance(payload, dict) else {}
    network = source_manifest.get("networkSummary", {}) if isinstance(source_manifest, dict) else {}
    if not isinstance(network, dict):
        return False
    status = str(network.get("status") or "")
    checked = int(network.get("checked") or 0)
    succeeded = int(network.get("succeeded") or 0)
    failed = int(network.get("failed") or 0)
    return status == "NETWORK_BLOCKED" and checked > 0 and succeeded == 0 and failed >= checked


def page_ok(
    port: int,
    timeout: float = 0.6,
    reject_blocked_news: bool = False,
    reject_codex_network_sandbox: bool = False,
) -> bool:
    url = f"http://127.0.0.1:{port}/launcher.html"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if not (200 <= response.status < 500):
                return False
    except (OSError, urllib.error.URLError, TimeoutError):
        return False

    utf8_probe = f"http://127.0.0.1:{port}/reports/P1008_DATABASE_KPI_GUIDE_20260629.md"
    try:
        with urllib.request.urlopen(utf8_probe, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if not (200 <= response.status < 500 and "charset=utf-8" in content_type):
                return False
    except (OSError, urllib.error.URLError, TimeoutError):
        return False

    api_probe = f"http://127.0.0.1:{port}/api/p1008/status"
    try:
        with urllib.request.urlopen(api_probe, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if not (200 <= response.status < 500 and "application/json" in content_type):
                return False
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if payload.get("serverVersion") != EXPECTED_SERVER_VERSION:
                return False
            server_context = payload.get("serverContext", {}) if isinstance(payload, dict) else {}
            if reject_codex_network_sandbox and server_context.get("codexNetworkSandbox"):
                return False
            source_manifest = payload.get("sourceManifest", {}) if isinstance(payload, dict) else {}
            if source_manifest.get("version") != "P1008_NEWS_SCAN_SOURCE_MANIFEST_v2":
                return False
            if reject_blocked_news and news_health_is_blocked(payload):
                return False
    except (OSError, urllib.error.URLError, TimeoutError):
        return False

    review_probe = f"http://127.0.0.1:{port}/api/p1008/review-package"
    try:
        with urllib.request.urlopen(review_probe, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            return 200 <= response.status < 500 and "application/json" in content_type
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def build_ports(start: int, end: int) -> list[int]:
    if start <= 0 or end <= 0 or start > 65535 or end > 65535:
        raise ValueError("port range must be between 1 and 65535")
    if end < start:
        raise ValueError("port range end must be greater than or equal to start")
    return list(range(start, end + 1))


def choose_port(ports: list[int], reuse_existing: bool = True) -> tuple[int | None, bool, list[int]]:
    blocked_news_ports: list[int] = []
    if reuse_existing:
        for port in ports:
            if page_ok(port, reject_blocked_news=False, reject_codex_network_sandbox=True):
                return port, True, blocked_news_ports
    for port in ports:
        if port_is_free(port):
            return port, False, blocked_news_ports
    return None, False, blocked_news_ports


def start_server(package_root: Path, port: int, log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("ab")
    server_script = Path(__file__).resolve().with_name("p1008_app_server.py")
    cmd = [
        sys.executable,
        str(server_script),
        str(port),
        "--bind",
        "127.0.0.1",
        "--directory",
        str(package_root),
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        cmd,
        cwd=str(package_root),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Open P1008 warroom via local app server.")
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--no-open", action="store_true", help="Verify/start the server but do not open a browser.")
    parser.add_argument("--fresh", action="store_true", help="Always start a fresh App server instead of reusing an existing localhost port.")
    parser.add_argument("--port-start", type=int, default=int(os.environ.get("P1008_PORT_START", DEFAULT_PORT_START)))
    parser.add_argument("--port-end", type=int, default=int(os.environ.get("P1008_PORT_END", DEFAULT_PORT_END)))
    args = parser.parse_args()

    package_root = args.package_root.resolve()
    page_path = package_root / "launcher.html"
    if not page_path.exists():
        print(f"[ERROR] Missing page: {page_path}")
        return 3

    if os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") == "1":
        print("[WARN] This App server is being started from the Codex network sandbox.")
        print("[WARN] Data/news connectors may show 0 success. For Owner use, double-click P1008_APP.bat in Windows.")

    try:
        ports = build_ports(args.port_start, args.port_end)
    except ValueError as exc:
        print(f"[ERROR] Invalid port range: {exc}")
        return 4

    port, already_running, blocked_news_ports = choose_port(ports, reuse_existing=not args.fresh)
    if port is None:
        print(f"[ERROR] No usable local port from {ports[0]} to {ports[-1]}.")
        print("[FIX] Close old P1008 browser/server sessions, or retry with a wider range:")
        print(f"      P1008_APP.bat --port-start {ports[-1] + 1} --port-end {min(65535, ports[-1] + 120)}")
        return 4
    if blocked_news_ports:
        skipped = ", ".join(str(item) for item in blocked_news_ports)
        print(f"[INFO] Skipped existing App server port(s) with NETWORK_BLOCKED news health: {skipped}.")
        print("[INFO] A fresh App server will be used so the crawler is not trapped in the old blocked session.")

    if already_running:
        print(f"[INFO] Local server already running on port {port}.")
    else:
        log_path = package_root / "logs" / f"http_server_{port}.log"
        proc = start_server(package_root, port, log_path)
        print(f"[INFO] Started local app server on port {port}; pid={proc.pid}; log={log_path}")
        for _ in range(6):
            if page_ok(port, reject_blocked_news=False):
                break
            time.sleep(0.35)
        if not page_ok(port, reject_blocked_news=False):
            print(f"[ERROR] Local app server did not respond quickly on port {port}.")
            print("[FIX] Close old Python/http.server processes or retry after a few seconds.")
            return 5

    url = f"http://127.0.0.1:{port}/launcher.html?stay=1&fs=1&reload={int(time.time())}"
    if args.no_open:
        print(f"[OK] Local app server verified: {url}")
        return 0

    if not open_immersive_browser(url):
        webbrowser.open(url, new=2)
        print("[WARN] Edge/Chrome app mode was not available; opened in the default browser.")
    print(f"[OK] Opened: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
