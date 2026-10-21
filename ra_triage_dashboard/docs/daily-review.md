# TE 标注进度

入口：每日数据 → 标注进度，`/manual/daily-review`。默认 BEV 图片网格，可切换
Camera、打开现有媒体查看器；不提交任何标签或触发媒体采集。页面使用现有主题、
语言切换和访问权限。静态资源版本 `manual-triage-588`。

## 数据口径

唯一 TE 来源为 `ra_review_result_new`，保留原始值。失败、未接起、out_of_scope
属于已填；整数 0 和字符串 None 不被误作空值。总数 = 已填 + 未填 + 未知。
完成率 = 已填/总数；空范围不展示假百分比。TE 状态只筛选卡片，不改变进度分母。
原因筛选同时作用于分母、卡片和导出。

* 1009：CST issue_time 日期，10/15 起至 T−2，严格版本边界与生产触发源准入。
  以 Trail 当前低置信/抽样集合为准，保留已 TE/RD 标注案例。0924 服务端拒绝。
* 0821：冻结的既有 312 条（低置信 227 / 抽样 85），不重新执行初始 TE/RD 排除。
* 采集器位于 RA 仓库 `tools/te_review_monitor/`。真实查询确认空 TE 字段会被省略，
  每轮通过完整/empty/not_empty 集合交叉验证，失败保留旧快照与原观测时间。
  快照记录成员增减、TE 修改/撤销和原因变化，不推测完成时间。

## 只读接口与边界

`settings.ra_auto_triage_root/reports/te_review_monitor` 下固定路径的原子 JSON
快照是唯一输入。API 不请求 Trail，不改 GT/Review/数据库，不影响主任务或健康检查。
文件最多 8 MiB、行数最多 20,000，验证版本、字段、唯一 ID 和路径边界；阻塞读取在
`asyncio.to_thread` 内。对外仅投影必要卡片字段，不返回任意原始字段或文件路径。

* `GET /api/daily-review` 与 `/api/daily-review/cases`
* `dataset=1009|0821`、`date=YYYY-MM-DD`、`reason=all|low|sample`
* `te_status=all|filled|unfilled|unknown`、`page=1..10000`、`size=1..100`
* 返回 scope、summary、date_options、result_distribution、source_status、
  last_success_at、snapshot_revision、items 和筛选后的 total。
* `GET /api/daily-review/export` 必须携带当前 revision；快照改变返回 409。
  同一 projection 导出所有筛选行，CSV 防公式注入；不拼接长 ID Trail 池链接。
* 正常最近数据超过 15 分钟、旧数据超过 70 分钟显示过期；同步失败保留已知结果。

前端每 30 秒读本地快照；隐藏标签页暂停，离页/范围切换取消请求和图片。
缩略图仅加载可见卡片，最多 4 个并发，失败单卡重试；沿用已有 480×270
缩略图编码/缓存，不另造 640×360 缓存。`kind=camera` 使用已发布帧中离 t0
最近的图片，缓存与 single-flight 有界，无视频抽帧或新媒体任务。

## 验证与发布

2026-10-21 隔离灰度端口 18797，独立 SQLite，关闭后台写任务并只读复用现有媒体。
合并主线后完整 Dashboard 测试：699 passed / 5 skipped；独立采集器 8 项通过。
真实 6 个 scope 共 725 条已校验摘要、全部分页、导出 ID 一致；0924/边界参数拒绝，
revision 不一致返回 409。浏览器验证与截图见本次调试报告。

正式发布使用既有版本化发布流程和精确的已推送 origin/master SHA；随后独立启用
采集器并进行公开入口验收。实际上线版本、采集状态和公开 SSO 验收结果以发布记录
为准。采集器通过独立 cron 每分钟执行 launch.sh --once，由内部时间门禁保持5分钟/
1小时频率及进程锁，不接入主任务 cron。不改数据库 schema，不替换当前 GT，不重复
导入 Run 或重新采集媒体。
