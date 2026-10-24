# Trail 更新记录与恢复

2026-10-25 已发布，运行 SHA `8b48e2353245e3b7cabba242f9ee114533ff6014`，静态缓存 `manual-triage-655`。生产恢复开关已按用户授权开启；详情见 [可视化与恢复启用验收](trail-history-visual-release-20261025.md)。首次 schema57 迁移见 [首次发布验收](trail-update-history-release-20261025.md)。

首次发布使用 `scripts/release_trail_history_20261025.py`，复用版本化 deploy_cloud 的锁、测试、灰度、进程、健康及应用回退门禁；保留旧 canonical checkout 的本地文件和占用的 8786，独立灰度使用 18789。仅允许 SHA-256 为 `54008df2790bc6910495524f0ae622da3e448248c9fe910b5a4195281a677e3a` 的新增 migration057；不放宽通用迁移白名单。停止 Dashboard 后进行新鲜备份、临时库恢复及逐表内容指纹比对，并在恢复库先演练 migration，再应用到生产。原有业务表保持内容指纹一致，新增审计表和 schema/change-revision 元数据除外。备份保留在独立 migrations 目录；应用失败回退旧代码，保留向后兼容的新表，不覆盖后续数据。后续可视化及开关启用使用 `scripts/release_trail_history_visual_20261025.py`，不再改 schema。

## 页面与覆盖范围

入口位于「系统管理 → Trail 更新记录」，路径 `/manual/trail-update-history`（沿用配置的 base path）。问题排除的汇总选中提交和按 Issue ID 提交成功后，在结果弹窗及页面提供「查看本次更新记录」，使用服务端返回的操作指纹直达详情；新提交清除旧链接，失败不展示成功入口。菜单位置不改变读取和恢复权限。页面沿用 Workbench 的主题变量、按钮、增强下拉、路由和中英文机制。默认显示本地审计记录，不因打开列表而查询 Trail。

支持按 Issue ID、操作人 LDAP、来源、执行结果和 CST 时间范围筛选、分页及详情深链。详情展示逐 Issue 的所属字段前后值、操作人、执行事件、恢复原因和关联恢复操作。缺失键、null、false 保持区别。新版记录起始时间和未接入来源在页面显式展示。

列表使用成功比例条、图标与状态文字；详情使用状态前后箭头和执行时间线。理由、操作标识及长说明按需展开，展开状态在语言切换时保留。恢复步骤可视化为“选择 → 预览 → 确认”，预览中的理由差异默认展开，任何选择或原因变更都要求重新预览。

本仓库页面写入路径盘点：

| 页面／来源 | 是否改变 Trail | 本次接入 |
| --- | --- | --- |
| 问题排除：汇总选中提交 | 直接修改 info 中 Workbench 所属的排除键 | 已接入 `exclusion_summary` |
| 问题排除：按 Issue ID 提交 | 直接修改同一 info 字段 | 已接入 `exclusion_direct` |
| Trail 更新记录：确认恢复 | 新增的逆向 info 写入 | 已接入 `rollback` |
| Case、Review、任务裁决 | 保存本地标注／裁决，本身不写 Trail | 无直接写入需要接入 |
| Runs、导入、对比、版本／每日结果展示 | 本地导入或读取；展示页面本身不写 Trail | 无直接写入需要接入 |
| Batch 的显式 AutoTriage 发布 | 调用外部 AutoTriage，外部下游可能写 Trail；不能据本仓库确认全部下游字段 | 未接入 |
| 每日回刷、抽样、外部 RD 同步 | 外部脚本／服务的写入，不是本页请求链 | 未接入 |
| Trail 原站、其他客户端 | 本仓库不能截获 | 未接入 |

因此，改动前有 **1 个直接写 Trail 的业务页面、2 条提交路径**；改动后增加 **1 个恢复页面、1 条写路径**。这不是 Trail 全站审计。外部来源后续需在其写入入口接入，不能通过本地状态猜测操作者或历史值。

代码入口：`app/routers/trail_update/{selection,routes}.py`，恢复路由 `app/routers/trail_history.py`，外部发布 `app/batch_prediction_worker.py` 的 `publish()`。

## 持久化与执行语义

- SQLite 独立 schema 与 PostgreSQL migration `057_trail_history.sql` 增加 `trail_operations`、`trail_operation_items`、`trail_operation_events`。数据库触发器拒绝更新和删除；新的操作和回执只追加。
- 外部写入前，先事务持久化操作身份和初始前后值；审计失败则不发出写请求。幂等重试不能替换首次快照。事件记录操作者和逐 Issue 结果。
- 只记录 `ra_stuck_auto_result_info.ra_triage_dashboard` 下的 `should_exclude`、`should_exclude_comment`、`operation_id`。不存凭据或其他模型 payload，不修改模型标签或 GT。自定义目标 info 字段使用配置；历史字段与当前配置不一致时禁止恢复。
- 旧 `trail_issue_exclusion_history` 在初始化时幂等导入为 `legacy`。保留原操作人、说明和结果，明确不是完整远端快照，永远不能据此恢复。
- 写入后进行回读；超时或不完整回执记录为待核验。请求取消时等待已开始的传输／回读／审计结束，之后才释放本进程提交锁。重启后可从持久记录重新核验，不盲目重放。

## 恢复操作

1. 已验证管理员选择该操作中已核验成功的 Issue，填写原因并预览。部分成功批次可只选择成功项。
2. 服务端重新读取 Trail，要求当前所属键（含原 operation_id）与被恢复记录的 after 精确一致。存在冲突时不给提交 token。
3. 预览绑定操作人、Issue 集合、原因、目标字段和快照，10 分钟有效；重启失效。确认提交前再次读取完整 info；预览后任何 info 变化都会阻止本次提交。
4. 恢复只反转所属业务键，保留当前非所属字段，写入新的 operation_id；产生关联到原记录的新审计操作，回读验证结果。不会删除原记录，也不会撤销本地标注、裁决或通知。

门禁同时要求：服务端已验证管理员、现有 writer 身份策略、同源 mutation 标记、`DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED` 和新增 `DASHBOARD_TRAIL_ROLLBACK_ENABLED=true`。后者默认 false。普通有读取权限的用户可以查看记录，不能恢复。重新核验目前也要求同样管理员门禁。

Trail 没有原子条件写入（CAS）。本实现的预览比对、提交前新查询、进程内锁和回读可以发现冲突，但不提供跨客户端或跨进程原子性，不能保证查询与写入之间绝无外部并发覆盖。

## API

| 方法与路径（均在配置的 API base path 下） | 用途 |
| --- | --- |
| `GET /api/trail-history` | 本地筛选列表、覆盖范围和恢复权限 |
| `GET /api/trail-history/{operation_id}` | 逐项快照、执行事件及关联恢复 |
| `POST /api/trail-history/{operation_id}/verify` | 新查询核验不确定结果；后续外部变更不能抹去历史成功回执 |
| `POST /api/trail-history/{operation_id}/restore-preview` | `{reason, issue_ids}`；仅允许选择本操作中成功项 |
| `POST /api/trail-history/{operation_id}/restore-commit` | `{preview_id, confirm: true}`；同 token 重试不重复发送已成功项 |

## 验证与上线边界

- Workbench 全量 Python 测试：854 通过、6 跳过；覆盖身份门禁、旧记录禁用、空值类型、部分批次、越界选择、冲突、幂等、审计故障、超时后重启核验。唯一 warning 是沙箱禁止写 pytest 缓存，不影响用例运行。需要 PostgreSQL 的用例另在临时空库执行。
- PostgreSQL 14 临时容器的全新空库执行全部迁移和既有集成用例；最终 22 项通过。复测时复用旧测试库曾触发既有固定夹具的 `reused` 断言，换全新空库后通过。
- 本机隔离 Chromium：320、390、1440px × 中英文 × 深浅主题，共 12 组；无页面／表单横向溢出和 JS 错误。另验恢复确认、深链刷新、语言切换保留草稿、共享下拉 Escape、空结果、失败状态和手机弹层边界。
- UI 的 Trail 传输为测试替身，数据库和 HTTP 路由使用真实本地实现。未写真实 Trail，未验证真机软键盘／触摸、Safari 或生产 SSO。
- 导航调整追加验证：52 项相关前端／base-path 测试通过；两个真实前端提交处理函数使用模拟响应验证精确详情跳转、系统菜单自动展开、关闭弹窗后保留入口、失败隐藏和新提交清除旧链接。新增入口再覆盖上述 12 组视口／语言／主题组合，手机点击高度 44px，无 JS 错误。
- 首次发布完成生产备份恢复演练及 schema57 迁移，97 张原有业务表指纹保持一致。后续按用户明确授权开启管理员恢复并部署可视化调整，最新云端完整测试 864 项通过、6 项跳过，生产三个恢复端点对未验证身份均返回 403。
