from __future__ import annotations

import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PACKAGE_ROOT / "launcher.html"


class LauncherOwnerPublishCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = LAUNCHER.read_text(encoding="utf-8")
        start = cls.source.index("async function copyApprovalPhrase()")
        end = cls.source.index("$('run-default').addEventListener", start)
        cls.copy_handler = cls.source[start:end]

    def test_copy_and_fill_control_is_present(self):
        self.assertIn('id="copy-approval-phrase"', self.source)
        self.assertIn('id="approval-copy-status"', self.source)
        self.assertIn("複製並填入", self.source)

    def test_handler_fills_exact_server_phrase(self):
        self.assertIn("const expected = (state.review || {}).ownerApprovalPhrase || '';", self.copy_handler)
        self.assertIn("input.value = expected;", self.copy_handler)
        self.assertIn("renderStatus();", self.copy_handler)

    def test_clipboard_has_local_fallback(self):
        self.assertIn("navigator.clipboard.writeText(expected)", self.copy_handler)
        self.assertIn("document.execCommand('copy')", self.copy_handler)
        self.assertIn("瀏覽器未允許剪貼簿，但不需要手動重打", self.copy_handler)

    def test_copy_control_never_calls_publish_endpoint(self):
        self.assertNotIn("/api/p1008/publish/formal", self.copy_handler)
        self.assertNotIn("ownerPublish()", self.copy_handler)
        self.assertIn("$('copy-approval-phrase').addEventListener('click', copyApprovalPhrase);", self.source)


if __name__ == "__main__":
    unittest.main()
