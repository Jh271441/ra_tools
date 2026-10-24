# 每轮增量展示 · 2026-10-25

参考：[Airbyte connection status](https://docs.airbyte.com/platform/cloud/managing-airbyte-cloud/review-connection-status) 的状态摘要/分项检查；[Dagster UI](https://dagster.io/docs/guides/operate/webserver) 的运行历史/详情分层。
方案比较：最新轮摘要+折叠历史适合本页的阅读顺序，手机自然重排；版本对照矩阵利于跨版本比对，但多版本和小屏仍容易出现宽表格。选前者，保留项目主题、字体、原生details与状态chip。

真实快照来源：现有GET /api/daily-cron，只读，没有增加Trail查询。10/24 07:00的1016仍为新22/补齐103/回刷103/入库37；1009全零压缩为一行。未改变后端计数、调度、队列、媒体、Runs或任务分配。

搜索框清除按钮：review-filters误把select箭头的29px右内边距应用到search，现恢复7px，保留浏览器原生清除与既有input监听。

浏览器：Codex内置浏览器，桌面1440、手机视口390/320；非真机。真实快照和隔离合成边界数据分别验证。发布与最终验证记录后补。

已通过60项相关测试（23项Cron/状态/前端shell＋37项媒体/Review/cache契约）。node --check与git diff --check通过。
Codex IAB实际覆盖：1440中文深色、1440英文浅色；390英文浅色、390中文深色；320英文浅色，失败/未知3版本、输入16轮仅显示14轮。真实样例与无变化版本已核对；接口不可用显示独立提示。语言切换保留展开状态。
自动刷新实测：原焦点23/10 19:00 summary，top372.59375px；新增轮次＋数字更新后仍在同summary，top372.59375px，scrollY2390→2832补偿新增内容高度，原2轮展开保留。相同快照不替换节点。
Issue搜索输入框1440/320视觉检查，右内边距7px；Escape清空正常。手机320无页面横向溢出（scrollWidth309/innerWidth320）。未做真机软键盘测试。

发布成功：2026-10-25 00:50:48 CST，runtime bdee0b525001b411712b97afcdc3b27e99967e18，cache645。完整云端836 passed/5 skipped；隔离SQLite灰度18789与PostgreSQL/schema56/policy通过。静态资源逐字节匹配候选。记录 /volume/home/workspace/ra_triage_dashboard_deploy/releases/20261024T164844Z-bdee0b525001/result.json，回滚de7da935398c1c38b5e72ca4f11e9c9654557fad。
发布前已在IAB打开并检查实际线上页面；发布后reload/new tab/direct DOM访问连续超时，故未完成发布后的登录态视觉复验。最终后图为已验收候选+真实只读快照，不能当作生产截图。
原manual-te-progress工作区的视频保存修复/裁决短文案未混入本发布，完整保留未提交修改。
