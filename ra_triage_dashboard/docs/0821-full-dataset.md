# 0821 full dataset

The frozen cohort is 2,005 distinct Trail Issues: exact release
`1.gen4-release-20260821.534`, trip_category 0, RA type 2/3, excluding CZ_TL.
This is not the narrower 312-member combined-review task.

The shared dataset picker unions three disjoint immutable source scopes:

| ID | Members | Scope |
|---|---:|---|
| 0821 | 1,242 | release0821_1242_20260908 |
| 0821-review-extra | 250 | manual_sidecar_0821-review-extra |
| 0821-trail-extra | 513 | manual_sidecar_0821-trail-extra |

Selecting0821 sends all three real IDs. User-requested follow-up: old0821 URLs,
saved selections and task-entry baseline selections upgrade to the full2005
membership once all three sources are registered. Other dataset partial unions
are unchanged. Explicit task IDs still restrict their own frozen members.
Source scopes, original task IDs, assignments, references, label revisions,
adjudications, comments, attachments, GT snapshots and model results are retained.
No old task is recreated, merged with a semantically different task, or reassigned.
New 513 members have no automatic assignment, inference, media capture or human
label import. Their initial GT is explicitly unobserved; normal read-only GT sync
can later observe OPS under the existing sparse contract.

Ordinary labeling Worksets now support exact multi-scope membership using the
existing frozen review_workset_scopes schema. All source scopes must be registered
and active. Campaign references continue to pin each source independently.

`scripts/expand_0821_dataset.py` prepares two identical complete Trail ID passes
and adds only missing members in one transaction. Before applying, require a
stopped-writer logical backup, disposable restore/all-table verification and an
actual migration rehearsal. The transaction rejects any change to old rows or
assignment/label tables. Full backups, source manifests, prior registry and
receipts belong on the cloud host, outside rolling retention and source trees.
Never restore a pre-migration backup over subsequent human work; fix forward.
