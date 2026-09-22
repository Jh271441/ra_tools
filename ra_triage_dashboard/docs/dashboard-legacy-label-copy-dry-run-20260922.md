# Historical Review label copy: field map and dry-run

Recorded: 2026-09-22 (Asia/Shanghai)

Scope: the isolated 8786 UX database only. Production data is excluded.

## Copy contract

| Legacy Review signal | Case-label destination | Rule |
| --- | --- | --- |
| Explicit `annotations.label` in 误触发 / 正确触发 / 无需协助 | Historical Case vote | Copy the label. |
| `review_status=reviewed` with no explicit label | Historical Case vote | Preserve “与 GT 一致” by copying the frozen GT value seen at import. |
| `review_status=needs_gt_review` | Shared Case state | Preserve the wording “GT 待复核” and freeze the import-time GT value/snapshot. |
| Multiple Runs, same Issue and reviewer, same label | One effective vote | Keep every source annotation and Run in provenance. |
| Multiple Runs, same Issue and reviewer, different labels | Reviewer conflict | Keep every source; do not select the newest value. |
| Different reviewers with one label | Shared resolved label | Preserve every reviewer vote. |
| Different reviewers with different labels | Conflict / pending adjudication | Do not convert import completion into label resolution. |
| No valid explicit label and no valid “与 GT 一致” GT value | No vote | The Review remains untouched and is counted as skipped. |

The copy excludes Review reason, missing evidence, task progress, ordinary Review
comments, Review completion state, and Review attachments. Source annotations,
comments, Runs, statuses, authors, timestamps, and revision history remain unchanged.

## Dry-run

Policy: `legacy-case-label-copy-v2`.

| Dataset scope | Reviews scanned | Effective label sources | Reviewer-dedup votes | Resolved Cases | GT 待复核 | Conflicts / pending adjudication | No-label sources skipped | Same-reviewer conflicts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| release0206_1326_20260729 | 50 | 43 | 41 | 33 | 6 | 3 | 7 | 0 |
| release0508_1071_20260729 | 45 | 39 | 30 | 22 | 15 | 2 | 6 | 1 |
| release0522_100_20260908 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| release0626_300_spotcheck | 12 | 11 | 9 | 7 | 5 | 1 | 1 | 0 |
| release0821_1242_20260908 | 103 | 101 | 87 | 42 | 30 | 10 | 2 | 3 |

`GT 待复核` can overlap a resolved or conflicting Case because it records the
historical GT relation, while conflict records vote agreement. Import batches
therefore report these dimensions separately.

## Sample audit set

| Scenario | Scope / Issue | Source evidence |
| --- | --- | --- |
| Same reviewer, same label | release0206 / `cn29141385` | reviewer `liangxianghui`, annotations 617 and 618, both 误触发 |
| Same reviewer, different labels | release0508 / `cn31974313` | reviewer `liangxianghui`, annotations 17, 774, 779; 正确触发 and 误触发 |
| Multiple reviewers agree | release0206 / `cn28972691` | three reviewers, all 误触发 |
| Multiple reviewers conflict | release0206 / `cn28927485` | `liangxianghui` 正确触发 versus `xuhaoxuan_i` 误触发 |
| 与 GT 一致 | release0206 / `cn28916185` | annotation 710, frozen GT 误触发 |
| GT 待复核 | release0206 / `cn28927485` | annotation 262, label 误触发 versus frozen GT 正确触发 |
| No label | release0206 / `cn28916185` | annotation 252, pending; skipped |

This report is the pre-write baseline. The applied migration must reproduce the
same counts, return zero new rows on replay, and leave the legacy Review hashes
and aggregates unchanged.
