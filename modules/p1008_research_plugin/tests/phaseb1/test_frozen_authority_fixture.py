from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import helpers
except ImportError:  # direct discovery with phaseb1 as the start directory
    import helpers


class FrozenAuthorityFixtureTests(unittest.TestCase):
    def test_materializes_every_manifest_path_from_frozen_revision(self) -> None:
        baseline = json.loads(
            helpers.AUTHORITY_BASELINES_PATH.read_text(encoding="utf-8")
        )["phaseB1Frozen"]

        with helpers.scratch("frozen-authority-all-paths-") as root:
            package = helpers.frozen_authority_package(root)
            manifest_path = package / "data" / "CSV_AUTHORITY_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            entries = [
                *manifest["authoritativeFiles"],
                *manifest["nonAuthoritativeFiles"],
            ]

            self.assertEqual(7, len(entries))
            self.assertEqual(
                baseline["manifestSha256"],
                hashlib.sha256(manifest_path.read_bytes()).hexdigest().upper(),
            )
            for entry in entries:
                relative = entry["path"]
                materialized = package / relative
                self.assertTrue(materialized.is_file(), relative)
                self.assertEqual(
                    entry["sha256"],
                    hashlib.sha256(materialized.read_bytes()).hexdigest().upper(),
                    relative,
                )
                frozen_blob = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(helpers.PACKAGE_ROOT),
                        "show",
                        f"{baseline['gitRevision']}:{relative}",
                    ],
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout
                self.assertEqual(frozen_blob, materialized.read_bytes(), relative)

    def test_modified_current_fx_cannot_leak_into_frozen_package(self) -> None:
        frozen_fx = b"Date,TWD_USD,Actionable\n2026-07-27,29.10,false\n"
        fx_digest = hashlib.sha256(frozen_fx).hexdigest().upper()
        manifest = {
            "authoritativeFiles": [],
            "nonAuthoritativeFiles": [
                {"path": "data/fx_trend_observations.csv", "sha256": fx_digest}
            ],
        }
        manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")

        with helpers.scratch("frozen-authority-current-fx-") as root:
            fake_package = root / "current-package"
            (fake_package / "data").mkdir(parents=True)
            (fake_package / "data" / "fx_trend_observations.csv").write_bytes(
                b"MUTABLE_CURRENT_PRODUCTION_FX"
            )
            (fake_package / "data" / "current-only-sidecar.csv").write_bytes(
                b"MUST_NOT_LEAK"
            )
            (fake_package / "contracts" / "p1008_research_plugin" / "v1.0").mkdir(
                parents=True
            )
            (fake_package / "rules").mkdir()
            (fake_package / "rules" / "RULE_STATUS_MANIFEST.json").write_text(
                "{}", encoding="utf-8"
            )
            baseline_path = root / "authority_baselines.json"
            baseline_path.write_text(
                json.dumps(
                    {
                        "phaseB1Frozen": {
                            "gitRevision": "frozen-revision",
                            "manifestSha256": hashlib.sha256(manifest_bytes)
                            .hexdigest()
                            .upper(),
                        }
                    }
                ),
                encoding="utf-8",
            )
            blobs = {
                "data/CSV_AUTHORITY_MANIFEST.json": manifest_bytes,
                "data/fx_trend_observations.csv": frozen_fx,
            }

            def fake_git_show(command, **_kwargs):
                relative = command[-1].split(":", 1)[1]
                return subprocess.CompletedProcess(command, 0, stdout=blobs[relative], stderr=b"")

            with (
                mock.patch.object(helpers, "PACKAGE_ROOT", fake_package),
                mock.patch.object(helpers, "AUTHORITY_BASELINES_PATH", baseline_path),
                mock.patch.object(helpers.subprocess, "run", side_effect=fake_git_show),
            ):
                package = helpers.frozen_authority_package(root / "output")

            self.assertEqual(
                frozen_fx,
                (package / "data" / "fx_trend_observations.csv").read_bytes(),
            )
            self.assertFalse((package / "data" / "current-only-sidecar.csv").exists())


if __name__ == "__main__":
    unittest.main()
