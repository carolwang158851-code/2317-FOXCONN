#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UTF-8 static server for the P1008 local warroom package."""

from __future__ import annotations

import argparse
import http.server
from pathlib import Path


UTF8_MIME_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".svg": "image/svg+xml",
    ".xml": "application/xml",
}


class P1008Utf8Handler(http.server.SimpleHTTPRequestHandler):
    """Serve text-like package files with explicit UTF-8 charset."""

    def guess_type(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        mime_type = UTF8_MIME_TYPES.get(ext)
        if mime_type:
            return f"{mime_type}; charset=utf-8"
        return super().guess_type(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve P1008 static files with UTF-8 content types.")
    parser.add_argument("port", type=int)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--directory", type=Path, default=Path.cwd())
    args = parser.parse_args()

    handler = lambda *h_args, **h_kwargs: P1008Utf8Handler(
        *h_args,
        directory=str(args.directory.resolve()),
        **h_kwargs,
    )
    httpd = http.server.ThreadingHTTPServer((args.bind, args.port), handler)
    print(f"Serving P1008 package at http://{args.bind}:{args.port}/ from {args.directory.resolve()}")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
