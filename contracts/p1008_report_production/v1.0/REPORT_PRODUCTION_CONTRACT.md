# P1008 Report Production Contract v1.0

The Phase B1 Report Builder consumes only a validated Analysis Packet, its
validated Evidence Manifest, the verified Authority Manifest identity, and the
approved report template embodied by the typed builder. It cannot read raw CSV
or raw news, search the web, recalculate undocumented metrics, replace Evidence
IDs, change evidence-bound conclusions, change the thesis state, or publish.

The report candidate contains twenty ordered sections and prioritizes one
investor question. Script candidates are downstream of the validated report;
they have no Authority, CSV, Evidence Packet, web, model, or database access.

All artifacts are deterministic UTF-8/LF files under
`runtime/report_production/<run_id>/`. They remain Owner-review candidates,
`actionable=false`, and never enter formal authority or Runtime SQLite.

Canva, video rendering, automatic publishing, scheduling, live synthesis, and
other event types are Phase B2 or separately authorized work and are outside
this contract.
