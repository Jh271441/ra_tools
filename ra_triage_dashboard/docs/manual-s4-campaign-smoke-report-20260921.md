# Manual S4 Campaign Smoke Report

**Date:** 2026-09-22
**Scope:** S4 Campaigns only. No S5/S6 work or production deployment was performed.
**Branch:** codex/review-campaign-s4
**Validated commit:** b75aa55 (source tree e86a99f)

## Final gate matrix

| Gate | Result | Evidence |
| --- | --- | --- |
| Campaign list/detail hidden mutual exclusion | **PASS** | Explicit hidden display rule; 64 frontend contract tests |
| Campaign deep-link state survives baseline changes | **PASS** | Campaign/group/purpose/lifecycle/query/baselines retained; 64 frontend contract tests |
| Native Model Review requires frozen Workset | **PASS** | Work Split adapter and Workset mismatch tests; 20 Work Split tests |
| Overlap, 1/1 and 1/2 per-Issue requirements | **PASS** | SQLite and disposable PostgreSQL fixtures |
| Atomic reassign, revision conflict and audit | **PASS** | Reassign reason/audit and idempotent replay |
| Close snapshot, write guard, reopen revision | **PASS** | Close snapshot frozen; closed writes rejected; reopen revision 3 |
| Draft activate/cancel/supersede | **PASS** | Lifecycle graph and terminal trigger checks |
| Two-Run Task Group | **PASS** | Shared Workset/reference and independent child progress |
| Case/Campaign/Run discussions | **PASS** | Shared dialog, locked replies, cross-channel rejects, read-only other Campaigns |
| Label Analysis axes and rationale themes | **PASS** | Scene, Trigger/interaction, Egress labels plus reason themes |
| 5000-member performance and EXPLAIN | **PASS** | Disposable PostgreSQL fixture with timings below |
| PostgreSQL rollback/race/idempotency | **PASS** | Disposable PostgreSQL fixture receipt |
| Full cloud pytest | **PASS** | 550 passed, 2 skipped in 49.81s |
| Production/S3 preservation | **PASS** | Read-only counts below |
| Native browser visual check | **BLOCKED** | Chrome reached ERR_CONNECTION_REFUSED because the local SSH loopback tunnel could not reach the cloud listener; HTTP/API/static acceptance passed |

## Isolated runtime

S4 runs from the versioned source under:

/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign/source-e86a99f/ra_triage_dashboard

It uses the private database manual_s4_smoke_20260921_campaign and binds only to 127.0.0.1:8786 at /manual-s4/. Its launcher is scripts/run_s4_smoke.sh in this repository and the private experiment root.

The S4 launcher uses production-mode request guards with Kylin ticket validation enabled and proxy identity headers disabled. The unauthenticated /api/session response was read_only=true, can_write=false, is_admin=false, and verified=false. Campaign mutation routes remain server-verified admin-only. Trail attribute writes, review writes, Batch prediction, AutoTriage push, DChat notifications, Trail startup sync, and GT sync were disabled.

## Migration and inventory

The post-migration inventory identified the S4 database and reported 8 legacy Work Splits. The source inventory SHA used for apply was:

4b71a9b8164fc2e6d3603fda1d98efef76802e59abb16582b1abf1c9f418d392

Migration 046_campaign_lifecycle_transitions.sql was applied to the S4 clone only. The resulting schema migration count is 46. Four Work Splits with explicit Labeling evidence were mapped to Labeling Campaigns; four ambiguous legacy Work Splits remain unclassified and read-only. The clone has 413 Issue rows and five active GT snapshots.

Post-migration reports are stored privately in the S4 experiment root:
- campaign-migration-apply-e86a99f.json
- campaign-inventory-post-migration-e86a99f.json

## Validation

The full cloud suite passed on the validated commit:

550 passed, 2 skipped in 49.81s

The HTTP acceptance check confirmed the health endpoint and the Campaign page HTML, Label Analysis tab, JavaScript, and CSS. The Campaign JavaScript sends the currently selected baseline IDs. The default 0508 selection returns 3 matching legacy rows; requesting all five configured baselines returns 8 rows: 4 explicit Labeling Campaigns and 4 ambiguous read-only rows. Label Analysis returned Issue totals of 1, 13, 15, and 24 across the four Labeling Campaigns.

The health response reported build b75aa55, base path /manual-s4, production mode, a read-only unauthenticated session, and all listed external writer/sync switches disabled. The sanitized HTTP result is stored as http-acceptance-b75aa55.json in the private S4 root. It also confirmed 8 Campaign UI markers, 4 explicit Labeling Campaigns, 4 ambiguous read-only rows, audit fields, discussion channels, and rationale themes.

A native Chrome check was attempted through the existing local tunnel. Chrome reached the S4 URL but reported ERR_CONNECTION_REFUSED when the tunnel could not reach cloud 8786; HTTP health, API, HTML, and static-asset checks passed.

The disposable PostgreSQL runner passed all 13 assertions. Receipt: data/campaign-smoke-receipt-20260922_cda5cb96.json. Timings: seed 5,000 Issues 1514.08 ms; create 5,000-member Campaign 4152.27 ms; list 135.81 ms; detail 276.50 ms; progress 129.22 ms; Label Analysis 264.45 ms. EXPLAIN ANALYZE execution: list 0.05 ms, detail members 14.40 ms, assignments 4.91 ms, label heads 0.04 ms.

## Preservation checks

All database checks used read-only PostgreSQL transactions and private 0600 URL files.

| Database | Issue rows | Migration count | Result |
| --- | ---: | ---: | --- |
| manual_s4_smoke_20260921_campaign | 413 | 46 | S4 clone migrated |
| manual_s3_smoke_20260921 | 413 | 44 | Preserved |
| ra_triage_dashboard | 4046 | 43 | Preserved |

Production port 8785 continued to report build 5fdc41ba8b0215170a8307237762e1ed50a9aaf2. The S3 launcher remains unchanged with SHA-256 6833d7951687f6a8ec7a13cec15cba9e435959e8025213dfffe5eb160b0ef780. Migration 046 and legacy mapping writes targeted only the S4 clone; S3 was queried read-only for preservation counts.

## Current state and restore

S4 is currently serving on loopback port 8786 with build b75aa55. The S3 database and artifacts remain intact. To restore the existing S3 smoke service, run the private experiment-root script:

/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign/restore_s3_8786.sh

The restore script verifies the pinned S3 launcher hash, refuses unknown listeners, stops only the verified S4 process, starts the existing S3 launcher in its own tmux session, and checks the S3 health/build and writer flags before reporting success.
