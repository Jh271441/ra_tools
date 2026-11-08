# Manual 全页面冷启动

基线为 `70f793b1` / cache774；本次前端版本 cache775。针对所有入口共享的启动依赖，而非只优化汇总。仿真看板不在本次范围内。

## 共享等待

此前浏览器下载并执行主脚本后才请求配置和登录态。现在 HTML head 在预加载主脚本的同时发出这两个同源 GET，主脚本通过原有 API 包装器消费一次响应。root 与 `/manual` 使用各自实际的 base path。

响应在到达时读取完整 body，完成后立即清除网络期限，避免主脚本下载较慢时误杀已完成的响应。挂起的早期请求保留从发起时算起的 6 秒期限，失败进入原有有界 GET 重试；登录跳转、401/403、非 JSON 和网络错误仍由既有解码与鉴权路径处理。带显式刷新、请求头、取消信号或其他 fetch 策略的请求另发新 GET，并退役未消费的早期读取。离开文档时清理未消费的请求。没有 localStorage 身份或业务响应缓存，也不跨页面会话复用响应。

部分页面此前在首个页面请求前等待模型 Run 目录，即便自身数据不依赖 Run。现在只有 Review、原因分析、模型结果、Run 对比和多 Run 评测的启动分支保留该依赖。其余分支可以加载自己的内容；共享概览在 Run 目录就绪后执行，并保留页面上下文校验。最终启动路由提交仍等待目录，避免其修改页面访问 epoch 后让有效的目录响应失效。页面权限、显式 Run、默认 Run 覆盖、数据集和任务范围规则保留。

## 验证口径

`tests/initial_reads.cjs` 运行真实 HTML 早期读取代码与 API 包装器，检查一次消费、显式刷新、请求策略、base path、body/期限、登录跳转、坏 JSON、网络中断恢复与 pagehide 清理。`navigation_races.cjs` 对模型无关和有关分支分别阻塞 Run 目录，验证首屏加载依赖、概览范围和切页所有权。旧版分别稳定触发缺少早期读取及 Trail 记录被目录阻塞的失败。

`startup_dependencies_browser.cjs` 使用真实完整 HTML、MANIFEST bundle、同样的 gzip、只读模拟 API 与独立 Chromium 上下文。`STARTUP_PROBE_ONLY=1` 扩展到全部 22 个路由条目（含旧入口重定向），其 `firstPageRequestMs` 只表示导航到首个页面数据依赖请求到达测试服务，不能称为内容可用。浏览器 Resource Timing 单独验证配置、登录态在主脚本下载期间发起，且各自只请求一次。

七个代表入口另以真实 DOM 内容为就绪条件，使用固定 300 ms 浏览器网络延迟、20 Mbps 带宽、三个全新上下文/版本，比较内容显示时间。响应抖动按端点固定注入；这些是受控实验，不是实际 VPN 丢包、生产端到端耗时或 p95。

| 内容显示中位数 | cache774 | cache775 |
| --- | ---: | ---: |
| 系统状态 | 1549 ms | 1269 ms |
| 用户管理 | 1541 ms | 1239 ms |
| 标注上传 | 1556 ms | 1259 ms |
| 原因聚类 | 2765 ms | 2184 ms |
| 任务分配 | 1573 ms | 1269 ms |
| 标注汇总 | 1552 ms | 1259 ms |
| Trail 更新记录 | 2478 ms | 1251 ms |

压缩后的主脚本为 493060 → 493437 bytes；对比没有改变资源压缩方式。固定响应延迟下六页改善约 18–21%，Trail 记录改善约 50%，与移除其额外目录等待一致。实验使用小型合成数据集，不能推导真实大数据集的服务端计算成本。

| 响应抖动下的内容显示中位数 | cache774 | cache775 |
| --- | ---: | ---: |
| 任务分配 | 1586 ms | 1266 ms |
| 标注汇总 | 1578 ms | 1270 ms |
| Trail 更新记录 | 1876 ms | 1271 ms |

复现示例（使用现有 Playwright 运行时）：

```bash
STARTUP_ROUTES=status,users,rd-results,analysis,assignments,summary,trail-history \
STARTUP_MEASURE_ONLY=1 STARTUP_TRIALS=3 STARTUP_NETWORK_MS=300 \
node ra_triage_dashboard/tests/startup_dependencies_browser.cjs
```

加 `STARTUP_TEST_REF=70f793b1` 加载基线资源；加 `STARTUP_NETWORK_PROFILE=jitter` 注入固定响应抖动。原始本地实验记录保存在 `reports/manual_cold_start_20261108/`（不提交）。

浏览器布局及交互沿用六入口 × 320/390/1440px × 中英文 × 深浅主题的 72 组验收，覆盖共享下拉、加载/禁用、分页/URL、语言切换和无页面横向溢出。检查范围不表示所有旧文案均完成翻译，也不代表真机、软键盘或 Safari/iOS。

性能记录和发布结果以本次证据及统一发布 receipt 为准。既有网络/VPN/代理和服务器流量策略没有更改。
