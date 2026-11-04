# Issue discussion release — 2026-11-04

Production `/manual` was promoted at **2026-11-04 22:35:37 CST** to
`ca23f49fd7fec9c474ecb81124badfaed529b24c`, **cache758**, PostgreSQL schema60.
Release: `/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261104T143102Z-ca23f49fd7fe/result.json`.

## Verified

- Full exact-SHA cloud gate: **1312 passed, 9 skipped**, 201.47s; isolated SQLite gray passed.
- Two PostgreSQL tests passed on a unique empty test database; test database removed.
  Covers schema58→60 with old comment preservation, cross-connection edits and submission
  deduplication, one notification outbox entry and exact historical image binding.
- Production comment182 on cn37255025 now returns the one original revision4136 image;
  all four original comment bodies, reply references and creation times match preflight.
- Eight served resources match exact release Git bytes. Database is persistent/healthy;
  overall status is healthy, writer flags are preserved. Anonymous image/receipt reads remain403.
- Real Chromium151 synthetic HTTP checks: 11 failure/recovery scenarios; 12 combinations
  of320/390/1440px × zh/en × dark/light, zero page errors. Seven wire retries yielded
  one synthetic comment. Existing drafts/reply/image nodes and focus survive locale changes.

## Migration and boundaries

The user explicitly authorized reading the current private connection configuration without
printing/exporting it, disposable DB creation/removal, stopped-writer backup/restore checks,
migration060 and production restart after automatic approval initially rejected the operation.
The new partial unique index is allowed only by the migration's exact path/content digest;
ordinary migration and backup/restore/gray/health guards remain.

The deployer stopped writers, created a fresh checksum-verified dump, restored it to a
unique disposable database, matched all public table counts, applied migration060, then
started production. Rollback of application code retains the backward-compatible columns/index.
See production-receipt.json for the backup and release record paths.

The first PostgreSQL image fixture used a text ID where PostgreSQL requires UUID; only the
test fixture changed. Both PostgreSQL checks and the complete exact-SHA release gate were
rerun on the corrected commit before promotion. The two prepared candidates and production
were never modified to make a gate pass.

No signed-in production clicking is claimed: CUA inventory timed out. Browser tests use
desktop Chromium viewports; no physical phone, Safari or soft-keyboard tests. Acceptance
posted no real business comments and sent no DChat notification.

Evidence: production-before.json, production-after.json, production-receipt.json,
validation.json, browser-results.json and the read-only readback.py.
