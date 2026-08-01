# P1008 Report Production Contract v1.0

The Phase B1 Report Builder consumes only a validated Analysis Packet, its
validated Evidence Manifest, the verified Authority Manifest identity, and the
approved report template embodied by the typed builder. It cannot read raw CSV
or raw news, search the web, recalculate undocumented metrics, replace Evidence
IDs, change evidence-bound conclusions, change the thesis state, or publish.

The report candidate contains twenty ordered sections and prioritizes one
investor question. Script candidates are downstream of the validated report;
they have no Authority, CSV, Evidence Packet, web, model, or database access.

Editorial validation is calculated, never defaulted. It fails closed on
missing or unresolved citations, unsupported numbers, blurred fact/inference
identity, prohibited intent claims, placeholders, duplicate sections, missing
next-validation or invalidation evidence, analysis-identity drift, script
provenance drift, or loss of the non-actionable boundary.

The 75-second candidate stores a deterministic duration receipt. Spoken
content assumes 4.2 pronounceable Traditional-Chinese characters, letters, or
digits per second; headings and the non-spoken compliance card are excluded.
60–75 seconds passes, 76–78 seconds passes with warning, over 78 fails, and
under 60 warns. `actionable=false` appears only in non-spoken compliance
metadata.

All artifacts are deterministic UTF-8/LF files under
`runtime/report_production/<run_id>/`. They remain Owner-review candidates,
`actionable=false`, and never enter formal authority or Runtime SQLite.

Canva, video rendering, automatic publishing, scheduling, live synthesis, and
other event types are Phase B2 or separately authorized work and are outside
this contract.
