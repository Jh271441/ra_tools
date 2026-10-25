# 同步本地“不排除”到 Trail / Sync local non-exclusion to Trail

这是本地 → Trail 的显式同步，不是导入 Trail 标记，也不是撤销某条历史写入。
This is explicit local → Trail synchronization, not importing a Trail marker or
restoring a historical operation.

## 预览 / Preview

`POST /api/trail-attribute-update/non-exclusion-preview`

```json
{"issue_ids": ["cn00000001"], "baselines": ["0508"], "model_run_id": ""}
```

Issue 为示例，不会自动提交。选择 1–200 个实际 Issue，数据集与可选 Run 必须包含
这些 Issue。沿用同源请求标记、已验证 SSO 写权限和汇总写入开关。
The Issue above is illustrative. Select 1–200 real Issues within the dataset
and optional Run. Existing same-origin, verified SSO writer and summary-write
gates apply.

只接受有效完整 Issue 裁决中的 `is_excluded=false`，或全部来源已形成有效结果且
所有有效排除意见均为 false 的 Case。未提交、未完成、冲突、过期裁决及任一有效
排除意见都不能被默认视为“不排除”。有效任务裁决替换其自身来源意见，完整 Issue
裁决沿用既有优先级。只读历史对账记录或旧 Run 标记不能单独授权此操作。
Requires a current full Issue decision with `is_excluded=false`, or resolved
sources whose effective exclusion votes are all explicitly false. Missing,
incomplete, conflicting or stale evidence cannot imply non-exclusion. Effective
task decisions replace their own source votes; full Issue decisions retain
existing precedence. Historical reconciliation or legacy Run flags alone never
authorize this operation.

预览返回 `intent=unexclude`、`payload_sha256`、10 分钟有效期、逐项 before/after、
本地来源版本和依据。目标为命名空间内 `should_exclude=false`；已有 false 无需再写，
返回 409。缺失/null 可明确设为 false；其它异常类型拒绝更新。
The preview returns `intent=unexclude`, `payload_sha256`, a 10-minute expiry,
per-Issue before/after and local source evidence. Existing false is already
matched (409); absent/null markers can become false; malformed types are rejected.

## 确认提交 / Confirm

`POST /api/trail-attribute-update/non-exclusion-commit`

```json
{"payload_sha256": "<preview receipt>", "confirm": true}
```

提交绑定预览操作人，重新检查本地来源及 Trail 当前值。任一来源或远端受管字段
改变时返回 409，必须重新预览。调用方不能通过提交体替换 Issue、目标值或来源。
The commit is actor-bound and revalidates local evidence and current Trail values.
Changed evidence or owned remote fields require a new preview (409). Commit
payloads cannot override the selected Issues, target or source.

仅修改 `ra_stuck_auto_result_info.ra_triage_dashboard.should_exclude`，并记录
`operation_id`。远端 `should_exclude_comment` 原样保留，**不是本次不排除的依据**；
本地理由作为审计来源单独记录。模型结果、GT、其它 info 字段及本地标注均不改变。
Only the namespaced exclusion boolean and audit `operation_id` change. The remote
comment is preserved verbatim as historical text, **not the new non-exclusion
rationale**; local rationale is retained separately in audit evidence. Model
results, GT, other info fields and local annotations remain unchanged.

复用写前持久审计、写后回读与幂等重试；不会触发通知。重启或预览过期后需重新预览。
Trail 不支持原子 CAS，进程锁和提交前检查不能保证跨系统并发原子性。
Existing durable pre-write audit, readback verification and idempotent retries
apply, without notifications. Restart/expiry requires a fresh preview. Trail has
no atomic CAS: process-local locks and preflight checks do not provide cross-client
atomicity.

通用 `selection-preview` 同样支持 `intent=unexclude`，`selection-commit` 可提交该
预览。专用接口拒绝其它 intent。不自动批量同步。
The generic selection endpoints also accept this intent; dedicated endpoints
reject other intents. No automatic bulk synchronization is performed.

## 页面入口 / UI entry

在“问题排除”明细区点击“同步不排除”，粘贴 1–200 个 Issue ID 或链接。
点击“预览改动”后，核对逐项的当前状态、本地结论依据和保留的 Trail 原理由，
再点击“确认写入”。当前数据集范围和已验证写权限始终生效；本地待裁决、
来源过期或仍有有效排除意见会被拒绝，不能把空列表或历史记录当成不排除依据。
取消不会写入，失败保留输入；结果弹窗可打开对应的 Trail 操作记录。

In Issue Exclusion details, choose **Sync non-exclusion** and paste 1–200 Issue
IDs or links. **Preview changes** shows each current state, local evidence and
the original Trail reason that will be preserved. Review these before choosing
**Confirm write**. Current dataset scope and verified write access apply.
Unresolved, stale or effectively excluded outcomes are rejected; empty lists and
historical records never imply non-exclusion. Cancel performs no write, errors
preserve input, and the result links to the corresponding Trail operation record.

## 排除页筛选口径 / Exclusion filter semantics

页面展示状态与更新资格共用当前候选数据：

| 状态 / State | 含义 / Meaning | 理由批量更新 / Reason batch update |
| --- | --- | --- |
| 理由可同步 / Reason ready to sync | 本地有理由且与 Trail 不同 / Local reason differs from Trail | 可选择，再预览确认 / Select, preview and confirm |
| 本地理由待补 / Local reason needed | 本地理由为空 / Local reason is empty | 先补充标注依据，保留远端原文 / Add local evidence first; preserve remote text |
| 已排除 / Excluded | 排除已生效；本地候选的理由一致，历史行仅表示远端排除 / Active exclusion; local reasons match, historical rows report remote exclusion only | 无理由变更 / No reason change |
| 待排除 / Awaiting exclusion | 本地排除，Trail 尚未排除 / Local exclusion is not active in Trail | 使用排除所选案例 / Use exclusion update |

视图决定候选范围。核对视图包含历史快照成员与本地候选，始终只读；不是全部
Issue 的实时扫描。不同筛选字段取交集，同一多选内取并集。筛选即时生效，重置
清除所有筛选条件并保留当前视图。折叠的高级筛选显示启用条件数。

图表按搜索、作者、GT、来源及本地/远端标记统计，不受自身状态选择或分页影响。
点击图例选中对应状态，再点一次取消。列表应用全部条件，分页和“选择本页可更新项”
只针对当前结果页。批量选择跨筛选保留，页外已选及已失效选择会明确提示。
理由作者优先使用实际理由来源作者。URL 刷新保留状态筛选；旧 `reason_update`
链接兼容展开为“理由可同步”和“本地理由待补”。

The view defines membership. Reconciliation combines historical snapshot members
and local candidates and is read-only, not a live scan of every Issue. Different
fields use AND; choices within one multi-select use OR. Filters apply immediately;
reset clears all filters while retaining the view. Collapsed advanced filters
show the number of active fields.

The chart follows search, author, GT, source and local/remote marker filters, but
not its own status selection or pagination. Click a legend to select its status;
click again to clear it. The list applies all filters. Pagination and select-page
eligibility use the current result page. Selection persists across filters, with
off-page and invalid selections reported explicitly. Reason authors prefer actual
reason provenance. Status filters survive URL reload; legacy `reason_update`
links expand to both ready-to-sync and local-reason-needed groups.
