# RA full-release reproduction status

Report state: **FINAL_WITH_QUALITY_FAILURES**.

Historical road behavior expects `positive_auto` and `negative_auto` to trigger, and `positive_manual` not to trigger. Business truth treats `positive_auto` plus `positive_manual` as positive and `negative_auto` as negative.

| Release | Job | Done / submitted | DPE | Pos-auto road | Neg-auto road | Manual road | Precision | Recall | Specificity | Accuracy | Quality | Complete |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| gen4-release-20260605 | 45191823 | 1785 / 1785 | 1785 | 90.30% | 88.19% | 78.72% | 74.13% | 80.71% | 11.81% | 64.03% | pass | yes |
| gen4-release-20260612 | 45192003 | 717 / 717 | 717 | 87.58% | 76.97% | 67.71% | 75.36% | 77.74% | 23.03% | 64.16% | pass | yes |
| gen4-release-20260618 | 45192287 | 990 / 990 | 990 | 88.45% | 85.03% | 81.29% | 81.63% | 76.67% | 14.97% | 66.26% | pass | yes |
| gen4-release-20260626 | 45192695 | 3584 / 3584 | 3584 | 92.41% | 84.12% | 74.83% | 80.83% | 82.13% | 15.88% | 69.67% | pass | yes |
| gen4-release-20260710 | 45192959 | 1460 / 1460 | 1460 | 84.38% | 78.17% | 79.37% | 80.95% | 69.29% | 21.83% | 61.10% | pass | yes |
| gen4-release-20260717 | 45193117 | 1294 / 1294 | 1294 | 84.48% | 68.25% | 77.88% | 84.31% | 71.47% | 31.75% | 64.99% | pass | yes |
| gen4-release-20260724 | 45193257 | 1385 / 1385 | 1385 | 85.83% | 74.73% | 72.51% | 86.70% | 75.56% | 25.27% | 68.81% | pass | yes |
| gen4-release-20260731 | 45193409 | 1505 / 1507 | 1505 | 81.32% | 65.28% | 73.22% | 87.79% | 69.05% | 34.72% | 64.65% | fail | no |
| gen4-release-20260807 | 45193549 | 1210 / 1210 | 1210 | 89.62% | 91.00% | 85.02% | 78.38% | 69.67% | 9.00% | 59.09% | pass | yes |
| gen4-release-20260814 | 45193633 | 853 / 853 | 853 | 89.66% | 86.58% | 76.22% | 80.63% | 76.28% | 13.42% | 65.30% | pass | yes |
| gen4-release-20260821 | 45193683 | 210 / 210 | 210 | 90.07% | 91.11% | 83.33% | 76.16% | 79.39% | 8.89% | 64.29% | pass | yes |

Overall submitted: 14995 / 15004 (excluded 9).
Completed with DPE: 14993 / 14993 (100.00%).
Road reproduction: positive_auto 88.08%, negative_auto 81.36%, positive_manual 77.03%.
Business truth: precision 80.94%, recall 75.80%, specificity 18.64%, accuracy 65.51%.
All submitted tasks terminal: yes.
All terminal and complete: no.
All quality gates passed so far: no.
Quality counts: cache hits 0, missing cache field 0, missing inference log 0, missing DPE output 0, missing output bag 0, failed evaluations 0, unexpected-warning tasks 0.
