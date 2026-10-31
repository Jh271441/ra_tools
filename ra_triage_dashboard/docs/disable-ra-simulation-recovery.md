# Manual-owned disable-RA simulation links

`/api/cases/{issue_id}/trail-metadata` can select a verified simulation result
owned by Workbench while preserving the original Trail task association. This
does not write Trail, labels, Review records or imported model results.

The operator-owned registry is
`DASHBOARD_DATA_DIR/disable_ra_simulations/links.json`. Publish updates with an
atomic rename, merging existing records and retaining the previous manifest and
the verification receipt in the recovery evidence directory. The runtime only
reads this file; there is no browser writer or arbitrary external URL setting.

```json
{
  "schema_version": 1,
  "links": {
    "cn35667619": {
      "source_task_id": "4523469300000031",
      "task_id": "5123456700000001",
      "task_version": 0,
      "status": "completed",
      "configuration_matches_source": true,
      "output_bag_count": 1,
      "verified_at": "2026-11-01T03:00:00+08:00"
    }
  }
}
```

The IDs above illustrate the schema. A real record must be published only after
checking successful completion, a readable newly produced bag, and matching
scenario, Binary, simulation flags and runtime against its source. A new batch
must pass the small-sample acceptance gate before bulk submission. Preserve the
source/new task IDs, simulation configuration and output retention in receipts.

The registry is bounded to 1 MiB. Missing, malformed, unverified or mismatched
source records fall back to the existing Trail link behavior. A verified local
record also works when optional Trail metadata is unavailable. A different
current Trail task supersedes the older local record. Local links carry
`disable_ra_simulation_source=manual` and the original task ID in the API for
provenance; the existing Animation button and bilingual layout are reused.
