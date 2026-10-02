"""Disposable, GET-only candidate runtime; never use the production launcher."""
import functools
import http.server
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
if not root.name.startswith(".tmp-scoring-runtime-") or (root / ".git").exists():
    raise SystemExit("Only a disposable non-Git scoring snapshot is permitted")
sys.path.insert(0, str(root / "tools"))
import p1008_app_server as app


class ReadOnlyHandler(app.P1008AppHandler):
    def do_POST(self):
        self._send_json(405, {"error": "Candidate verification is GET-only"})


ReadOnlyHandler.manager = app.P1008JobManager(root)
http.server.ThreadingHTTPServer(
    ("127.0.0.1", 8768), functools.partial(ReadOnlyHandler, directory=str(root))
).serve_forever()
