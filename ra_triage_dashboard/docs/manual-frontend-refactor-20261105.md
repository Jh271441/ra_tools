# Manual 前端模块整理（2026-11-05）

## 范围与基线

本轮整理 `/manual` 的统计、讨论、详情媒体和 Review 编辑流程。首轮在原工作区
验证拆分；发布候选基于 `origin/master` 的
`61665c66dfcabcda6704bb9a7f4f8129ec37884e` 重新提取，以保留线上
`219a8112f02f78e74ee0c81cf5ae715387685582` 的全部修复，以及最新恢复说明。
原工作区的其他未提交修改保留，仿真看板另行处理。没有数据库、依赖或 Git
历史变更；发布使用标准完整测试、隔离灰度及精确 SHA 部署流程。

目标是让后续修改能定位到负责该行为的模块，避免继续向统计、详情媒体和表单
三个文件叠加不相关逻辑。沿用已有 classic script、共享组件、国际化和响应式样式。

## 职责归属

| 模块 | 维护范围 |
| --- | --- |
| `analysis.js` | 统计请求、筛选、表格和分页控制 |
| `analysis-charts.js` | 饼图、状态图、混淆矩阵及联动悬停 |
| `issue-discussion.js` | 各入口共享的 Issue 讨论、回复、图片、提交回执与重试 |
| `detail-media.js` | BEV/Camera 帧、时间轴、媒体区域和异步媒体展示 |
| `bev-video.js` | 共享视频渲染、播放意图、切源、跳转、监听器和播放器清理 |
| `detail-trail.js` | 外链、RA Event 弹窗、元数据缓存及详情上下文校验 |
| `review-history.js` | Review/模型输出历史、历史弹窗及版本操作 |
| `review-expected-output.js` | 输出选项、Tag 推断、冲突校验和模型复核进度 |
| `review-combined.js` | 联合上下文加载、请求归属、Case/模型字段回填与可提交状态 |
| `review-form.js` | 详情/编辑表单渲染、已有内容展示和保留草稿的语言刷新 |
| `review-navigation.js` | Issue 加载、预取、媒体渐进加载、取消、相邻导航和详情清理 |
| `review-shortcuts.js` | Review 快捷键、讨论入口及 Issue ID 复制 |
| `review-submit.js` | 普通/联合提交、提交锁、保存后筛选队列对齐 |

发布候选中，`analysis.js` 从 1911 行降至 539 行，`review-form.js` 从 1885 行降至
612 行，`detail-media.js` 从 1764 行降至 498 行。保留主线的分段视频、帧保留、
默认暂停、BEV/Camera 快捷键、图片继承和保存后队列导航。

## 加载与维护约定

- 模块按唯一的 `MANIFEST` 顺序合并传输，最后由 `bind-bootstrap.js` 启动。
  服务启动时生成并预压缩 `/static/app-bundle.js`，`app.js` 只加载这个包。
  源码继续按职责拆分；新模块只声明函数和原有顶层状态。
- `core-base.js` 中的通用选择器、定位和增强机制继续由所有页面共享。
- 表单渲染、上下文回填、提交与导航各有单一归属；需要跨职责协作时调用已有
  函数，不复制函数、加覆盖版本或在旧文件保留转发壳。
- 讨论保留 `openAnalysisDiscussion` 等既有入口名称，供 Review、标注、统计和
  深链共用；函数名称不意味着讨论仍由统计控制器持有。
- 历史、播放、草稿和请求取消逻辑一并迁移。原有函数签名、状态键、API/URL
  参数、权限校验、表单节点和中英文文案保持原有语义。
- 定向测试读取实际归属模块；浏览器全流程测试继续读取真实 `MANIFEST`。
- 初次重构缓存版本为 `manual-triage-762`；首开性能修复为 `manual-triage-763`。

## 验证

首轮工作区基线的 82 项前端契约测试通过。发布候选重新以最新主线快照为基线，
分别在 Node VM 中加载重构前后的模块，**192 个函数**的 `toString()` 逐个相同，
**14 处顶层状态初始化值**相同；没有用旧工作区代码覆盖线上新逻辑。

| 检查 | 结果 |
| --- | --- |
| 前端契约与模块边界 | 86 项通过，包括所有模块恰好注册一次、全局声明单一归属、根路径和 `/manual` 的顺序预加载/执行 |
| 标注/复核交互、GT 图、手机输入、语言刷新及基础路径 | 17 项通过 |
| 快捷键、视频源及 RA Event 焦点行为 | 29 项通过 |
| 联合任务绑定、预取缓存和过期上下文 | 随发布完整测试门禁验证 |
| Node 行为回归 | 11 组通过：视频、联合回填、上下文重试、讨论归属、导航竞争、Trail 缓存、IME、后台图片提交、GT 作用域、定位待处理 Issue、保存后完整筛选队列导航 |
| 语法及差异检查 | 修改的 Python、JS/CJS 文件通过语法检查；`git diff --check` 通过 |

定向门禁（在仓库根目录执行）：

```bash
PYTHONPATH=ra_triage_dashboard/tests python3 -m unittest discover -s ra_triage_dashboard/tests -p 'test_frontend*.py' -q
PYTHONPATH=ra_triage_dashboard/tests python3 -m unittest test_label_review_interactions test_gt_queue_frontend_behavior test_mobile_interaction test_review_issue_decision_behavior test_base_path -q
node ra_triage_dashboard/tests/video_performance.cjs
node ra_triage_dashboard/tests/combined_review_hydration.cjs
node ra_triage_dashboard/tests/combined_review_context_ui.cjs
node ra_triage_dashboard/tests/discussion_scope.cjs
node ra_triage_dashboard/tests/navigation_races.cjs
node ra_triage_dashboard/tests/trail_metadata_cache.cjs
node ra_triage_dashboard/tests/review_ime.cjs
node ra_triage_dashboard/tests/background_case_uploads.cjs
node ra_triage_dashboard/tests/version_gt_ui.cjs
node ra_triage_dashboard/tests/next_pending_task.cjs
node ra_triage_dashboard/tests/review_save_queue.cjs
```

### 浏览器回归

macOS 无头 Chromium **148.0.7778.96**，真实 shell、模块、样式与本地合成 API/
视频；合计 72 组视口/语言/主题/页面组合，页面脚本错误为 0。

- `combined_review_hydration_browser.py`：320/390/1440px × 中英文 × 深浅主题，
  12 组；补查延迟上下文、加载失败/重试、主动清空字段及未保存编辑保留。
- `discussion_reliability_browser.cjs`：12 组布局；11 种丢响应、超时、权限、
  手动重试和提交后 UI 失败场景，保留回复对象、草稿与图片且不重复创建评论。
- `ra_event_navigation_browser.cjs`：Review/标注页合计 24 组；4 类刷新检查，
  包括忙状态去重、保留搜索、失败保留旧数据和忽略已离开弹窗的响应。
- `video_playback_intent_browser.cjs`：Review/标注页合计 24 组；检查播放意图、
  加载中取消、快速切源、焦点快捷键、弹窗接管及退出清理。

RA Event 的 200ms 忙状态断言、视频快速切源的固定延迟断言，在重构前快照上
也失败。本轮将它们改为由测试显式放行响应，并隔离每组视频源 URL，保留原有
断言和异常路径；不依赖机器速度或媒体缓存决定测试能否观察到等待态。

浏览器使用响应式视口，不是真机或 Android/iOS 模拟器；未覆盖 Safari、真实
软键盘和生产登录交互。本轮没有改 API、数据库或部署代码。发布完整测试和隔离灰度的权威结果保存在
`/volume/home/workspace/ra_triage_dashboard_deploy/releases/<UTC时间-SHA>/result.json`；
线上 SHA 与发布回执见维护技能的 `CURRENT_HANDOFF.md`。既有后端和其他对话的
未提交修改不计为本轮重构内容。

### 首开性能修复（cache763）

用户反馈首次打开/刷新变慢后，确认首轮验收遗漏了真实加载入口的性能检查。
源码拆分使启动模块请求从 65 增至 74，页面要等全部模块执行后才开始请求业务
数据；发布的全局缓存版本变化还会使第一次访问重新下载全部静态资源。
代码总量仅增加约 1.4KB，但更多独立请求延长了冷缓存等待。

修复保留源码和经典脚本的原顺序，在服务启动时一次性生成合并包及 gzip 表示，
每次请求复用内存中的字节。浏览器只请求入口和合并包，CSS 仍沿用原有顺序。
包提供表示独立的 ETag、304、HEAD、Vary 和既有 immutable 缓存策略；原模块
URL 保留，已有页面仍可使用原入口。

受控 macOS Chromium 148.0.7778.96、本地 HTTP/1.1、120ms 延迟及 20Mbps
下行，3 次中位数如下。指标为导航至开始发起首个业务 API，接口响应被测试阻塞，
不是完整数据渲染耗时，也不是线上 p95：

| 版本 | 冷缓存 | 缓存命中后刷新 | 冷缓存静态请求数（含 CSS） |
| --- | --- | --- | --- |
| 重构前 cache761 | 2134ms | 279ms | 87 |
| 首次重构 cache762 | 2506ms | 326ms | 96 |
| 合并传输 cache763 | 1048ms | 290ms | 23 |

原始对比：`/tmp/manual-startup-investigation-20261105/startup-fix-comparison.json`。
新增回归检查限制入口只加载一个有序包，并验证包与 MANIFEST 顺序一致、经典
脚本可解析、gzip/identity/304/HEAD 正确。业务函数、API、权限、数据库和仿真
看板保持原有契约。公开入口的匿名浏览器计时没有获得可用的启动结果，不计为
已登录生产验收；线上版本和资源字节仍按标准发布回执及只读核对确认。
