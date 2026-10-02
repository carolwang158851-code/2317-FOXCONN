"""Preserve frozen UI hashes while testing the explicitly authorized consumer repair.

Legacy pre-repair hashes describe Windows CRLF checkout bytes; Command Center's
historical hash uses LF bytes. These explicit identity domains remain unchanged;
they are not baselines for the newly authorized UI. Expected hashes stay fixed.
Current research/MIDR formula bodies and legacy weights must remain identical.
"""
import hashlib
import subprocess

BASE = "75320cad1e8b8a30b837cacb2593f936dd57f29b"


def base_blob(root, relative):
    return subprocess.check_output(["git", "-C", str(root), "show", BASE + ":" + relative])


def historical_ui_sha(root, relative):
    blob = base_blob(root, relative)
    if relative == "ui/P1008_WARROOM_COMMAND_CENTER_v24.html":
        historical_bytes = blob  # Fixed LF domain, not automatic hash selection.
    elif relative in {"src/index_p1008_v7.source.html", "index_p1008_v7.html"}:
        historical_bytes = blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    else:
        raise AssertionError("No authorized historical UI identity domain: " + relative)
    return hashlib.sha256(historical_bytes).hexdigest().upper()


def function_body(text, name):
    start = text.index("function " + name + "(")
    start = text.index(") {", start) + 2
    depth = 0
    for index in range(start, len(text)):
        depth += (text[index] == "{") - (text[index] == "}")
        if depth == 0:
            return text[start:index + 1]
    raise AssertionError("Unterminated function: " + name)


def assert_current_formula_protection(case, root):
    path = "src/index_p1008_v7.source.html"
    frozen = base_blob(root, path).decode("utf-8").replace("\r\n", "\n")
    current = (root / path).read_text(encoding="utf-8")
    for name in ("calculateQualityBreakdown", "calculateQualityScore", "calculateDimasCap",
                 "calculateMidrObservation", "buildRtmMetadata", "calculateChipScore", "clampScore"):
        case.assertEqual(function_body(frozen, name), function_body(current, name), name)
    def legacy_dimensions(text):
        start = text.index("const fundScore = clampScore(quality)")
        return text[start:text.index("];", start) + 2]
    case.assertEqual(legacy_dimensions(frozen), legacy_dimensions(current))
    case.assertIn("fetchOptionalJson('/api/p1008/scoring-state')", current)
    case.assertIn("item.formal_eligible && Number.isFinite(item.weighted_contribution)", current)
