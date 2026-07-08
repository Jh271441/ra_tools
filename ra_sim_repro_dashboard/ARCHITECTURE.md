# RA Sim Repro Dashboard Architecture

本文档描述 RA 仿真复现看板的系统边界、数据链路、后端服务、前端结构、存储模型、刷新机制和部署方式。该看板是独立目录下的新应用，和 `model_release_pipeline` 没有运行时依赖。

## 1. 目标与边界

### 目标

看板用于评估 RA stuck 自触发模型在离线仿真中的复现能力，并把仿真结果折算为准召指标：

- 当前版本仿真复现率。
- 当前版本和前序版本的 Precision / Recall / F1 趋势。
- Source GT 与仿真估计的 TP / FP / FN / TN 对比。
- Scenario / issue 级别明细，支持按版本、根因、触发类型、TP/FP/FN/TN 查询。
- 每个 issue 可以查看对应 scenario、job、source labels、仿真触发值和同场景跨版本结果。

### 非目标

- 不复用 `model_release_pipeline` 的代码和数据结构。
- 不做 bag frame timeline 级别解析。
- 不在前端直接调用内部 Voyager / Trail / Scenario API，所有内部 API 由后端代理和归一化。
- 不提交真实 cookie、token、个人登录态或生产数据库 dump。

## 2. 技术栈

| 层 | 技术 | 说明 |
| --- | --- | --- |
| Frontend | React, Vite, TypeScript | 单页应用，开发端口 `5174` |
| UI | Tailwind CSS, local shadcn-style components | Apple-like light/dark 蓝色风格 |
| Charts | Recharts | 折线图、柱状图、tooltip、数据标签 |
| Table | TanStack Table | issue/scenario 明细表 |
| i18n | i18next, react-i18next | 中文/英文切换 |
| Backend | FastAPI, Pydantic, SQLAlchemy | REST API 与刷新任务编排 |
| DB | PostgreSQL, SQLite | Docker 使用 PostgreSQL，本地开发可用 SQLite |
| Queue | Redis, RQ | 异步刷新任务与刷新锁 |
| Deployment | Docker Compose | backend, worker, frontend, postgres, redis |

## 3. 总体架构

```mermaid
flowchart LR
  User[User Browser] --> Frontend[React Frontend<br/>Vite :5174]
  Frontend -->|/api/dashboard/*| Backend[FastAPI Backend<br/>:8000]

  Backend --> DB[(PostgreSQL / SQLite)]
  Backend --> Redis[(Redis)]
  Backend -->|enqueue| Worker[RQ Worker]
  Worker --> DB
  Worker --> Redis

  Worker --> ScenarioAPI[Scenario API<br/>label query]
  Worker --> SimAPI[Voyager / Trail query_report]
  Worker --> IssueAPI[Issue API]
  Worker --> Mock[Mock JSON<br/>data/mock]

  Backend --> Config[config/versions.yaml]
  Worker --> Config
```

运行时职责：

- Frontend 只负责展示、筛选、交互和调用后端 API。
- Backend 提供同步查询 API、创建刷新任务、管理数据库连接。
- Worker 执行真实刷新，包含 source scenario 拉取、sim job 拉取、issue 元数据拉取、指标计算和快照写入。
- PostgreSQL 存储版本、scenario、issue、scenario-version 结果、快照和刷新任务。
- Redis 用于 RQ 队列和刷新互斥锁。

## 4. 目录结构

```text
ra_sim_repro_dashboard/
  README.md
  ARCHITECTURE.md
  docker-compose.yml
  .env.example
  config/
    versions.yaml
    versions.example.yaml
  data/
    mock/
      issues.json
      sim_job_*.json
  backend/
    Dockerfile
    requirements.txt
    app/
      main.py
      config.py
      database.py
      models.py
      schemas.py
      metrics.py
      worker.py
      api/routes.py
      services/
        refresh.py
        sim_result_client.py
        scenario_client.py
        issue_client.py
        cache.py
    tests/
      test_metrics.py
      test_refresh.py
  frontend/
    package.json
    vite.config.ts
    src/
      App.tsx
      api/client.ts
      components/
        Overview.tsx
        IssuesTable.tsx
        IssueDetail.tsx
        TopControls.tsx
        ui/
      i18n.ts
      index.css
      types.ts
```

## 5. 配置模型

版本配置在 `config/versions.yaml`：

```yaml
current_version: "gen4-release-20260417"
compare_versions:
  - "gen4-release-20260327"
  - "gen4-release-20260403"
  - "gen4-release-20260410"

versions:
  "gen4-release-20260417":
    label: "release20260417"
    binary: "gen4-release-20260417"
    sim_plan: "lxh_ra_stuck_release_20260417-openloop"
    sim_jobs:
      positive_job_id: 39467319
      negative_job_id: 39367009
    scenario_sets:
      positive:
        labels: [...]
        manual_labels: [...]
      negative:
        labels: [...]
        manual_labels: [...]
        normal_stop_labels: [...]
    source_gt_counts:
      auto_trigger_tp: 582
      manual_trigger_fn: 254
      auto_trigger_fp: 359
```

关键字段：

- `current_version`: 首页高亮和 summary 的当前版本。
- `compare_versions`: 当前版本前面参与趋势对比的版本。
- `sim_jobs.positive_job_id`: 正样本场景集仿真 job。
- `sim_jobs.negative_job_id`: 负样本场景集仿真 job。
- `scenario_sets`: Scenario API 的 label 查询组合。
- `source_gt_counts`: Scenario API 不可用时的 GT fallback。
- `sim_eval`: 仿真 API 不可用时的预估指标 fallback。

配置会被 `backend/app/config.py` 读取并计算 `config_hash`，刷新任务和快照都会记录该 hash。

## 6. 数据来源与优先级

### 6.1 仿真结果

`SimResultClient` 的读取优先级：

1. `data/mock/sim_job_{job_id}.json`。
2. Voyager `query_report`，使用 `VOYAGER_COOKIE`。
3. Trail signed `query_report`，使用 `TRAIL_APP_ID` / `TRAIL_APP_TOKEN`。

正负样本 job 被归一化为同一结构：

- positive job: `dataset_role=positive`, `road_triggered=true`
- negative job: `dataset_role=negative`, `road_triggered=false`

仿真触发信号：

```text
Base.dpe_assist_channel_triggered.value >= 1 => sim_triggered=true
Base.dpe_assist_channel_triggered.value < 1  => sim_triggered=false
```

代码中归一化字段名为 `dpe_assist_channel_triggered`。对于 `0`、`false` 这类有效值，归一化逻辑必须保留，不能用 truthy fallback 覆盖。

### 6.2 Source GT

`ScenarioClient` 使用 `scenario_sets` 中配置的 label 组合查询 Scenario API：

- `positive.labels`: 正样本自触发，计入 source TP。
- `positive.manual_labels`: 正样本人工触发，计入 source FN。
- `negative.labels`: 负样本自触发误触发，计入 source FP。
- `negative.manual_labels`: 负样本人工触发误触发，作为无关 issue。
- `negative.normal_stop_labels`: 正常等待，计入部分 TN。

同一个 scenario 可能命中多个 label 组合，后端会累计 `source_groups` 和 `source_labels`，避免覆盖。

### 6.3 Issue 元数据

`IssueClient` 的读取优先级：

1. `data/mock/issues.json`。
2. Issue API，使用 `ISSUE_APP_ID` / `ISSUE_APP_TOKEN`。
3. fallback issue row，至少保留 `issue_id`。

## 7. 刷新链路

```mermaid
sequenceDiagram
  participant FE as Frontend
  participant API as FastAPI
  participant Redis as Redis/RQ
  participant Worker as Worker
  participant DB as Database
  participant Ext as Internal APIs

  FE->>API: POST /api/dashboard/refresh
  API->>DB: create RefreshJob(status=queued)
  API->>Redis: enqueue app.worker.run_refresh_job
  API-->>FE: 202 RefreshJob
  Worker->>DB: load job, mark running
  Worker->>DB: sync versions from config
  loop each version
    Worker->>Ext: query source scenarios by labels
    Worker->>Ext: query positive/negative sim jobs
    Worker->>DB: replace version results if sim rows loaded
    Worker->>DB: keep old results if sim API failed
  end
  Worker->>Ext: query issue metadata
  Worker->>DB: write DashboardSnapshot
  Worker->>DB: mark job completed/failed
  FE->>API: GET /api/dashboard/refresh/{job_id}
```

关键保护：

- 使用 Redis lock `ra:lock:refresh:{config_hash}` 防止同配置并发刷新。
- 如果 RQ 入队失败，FastAPI 会降级为 background task，并把错误写入 job message。
- 如果某版本 sim API 失败，保留该版本旧结果，不删除旧明细。
- 如果 source scenario API 失败，继续使用 `source_gt_counts` fallback。

## 8. 指标与分类

### 8.1 混淆矩阵

| road_triggered | sim_triggered | label | 含义 |
| --- | --- | --- | --- |
| true | true | TP | 源场景触发，仿真也触发 |
| true | false | FN | 源场景触发，仿真未触发 |
| false | true | FP | 源场景不应触发，仿真触发 |
| false | false | TN | 源场景不应触发，仿真也未触发 |

### 8.2 准召公式

```text
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
f1        = 2 * precision * recall / (precision + recall)
```

仿真复现率：

```text
sim_repro_rate = reproduced_auto_trigger_cases / source_auto_trigger_cases
```

其中：

- `source_auto_trigger_cases`: source group 为 `positive_auto` 或 `negative_auto` 的场景。
- `reproduced_auto_trigger_cases`: 上述 source 自触发场景中 `sim_triggered=true` 的数量。
- `positive_manual`: 人工触发正样本只参与 `recall = TP / (TP + FN)`，不进入仿真复现率分母。

### 8.3 触发类型与根因

`metrics.py` 负责归一化：

- `trigger_type`: `MODEL`, `FN`, `FP_SUPPRESSED`, `OTHER`, `NONE`
- `root_cause`: `REPRODUCED`, `TRUE_NEGATIVE`, `FALSE_POSITIVE`, `FP_RULE_SUPPRESS`, `SIM_DIVERGENCE`, `MODEL_OR_COUNTER_INSUFFICIENT`, `UNKNOWN`

`MODEL_FP` 表示 FP suppression 证据，不单独证明模型成功触发。

## 9. 数据库模型

### versions

版本元信息表。

| 字段 | 说明 |
| --- | --- |
| `version_key` | 主键，例如 `gen4-release-20260417` |
| `label` | 展示名 |
| `sim_job_id` | 兼容单 job 模式 |
| `baseline_job_id` | 兼容 baseline 对比 |
| `sort_order` | 趋势图排序 |
| `is_current` | 是否当前版本 |
| `metadata_json` | config 中的完整版本配置和运行时 source 状态 |
| `last_refreshed_at` | 最近刷新时间 |

### scenarios

Scenario 基础信息表。

| 字段 | 说明 |
| --- | --- |
| `scenario_id` | 主键 |
| `scenario_name` | 场景名 |
| `issue_id` | 关联 issue |
| `signature` | 场景 signature |
| `raw_info` | source groups、labels 等原始信息 |

### issues

Issue 元信息表。

| 字段 | 说明 |
| --- | --- |
| `issue_id` | 主键 |
| `issue_topic` | issue 标题 |
| `status` | 状态 |
| `priority` | 优先级 |
| `poi` | 地点 |
| `issue_time` | 时间 |
| `url` | Voyager issue URL |
| `raw_issue` | Issue API 原始返回 |

### scenario_version_results

核心明细表，每个 version + scenario 一条记录。

| 字段 | 说明 |
| --- | --- |
| `version_key` | 版本 |
| `scenario_id` | 场景 |
| `issue_id` | issue |
| `road_triggered` | Source GT 是否触发 |
| `sim_triggered` | 仿真是否触发 |
| `reproduced` | 是否复现 |
| `precision_label` | TP / FP / FN / TN |
| `trigger_type` | 触发类型 |
| `root_cause` | 根因 |
| `model_score_max` | 模型最大分 |
| `threshold` | 阈值 |
| `unstuck_status` | 规则/状态 |
| `fp_reasons` | FP 相关原因 |
| `fn_reasons` | FN 相关原因 |
| `raw_metrics` | 仿真结果与 source labels 原始归一化数据 |

约束：

```text
unique(version_key, scenario_id)
```

### dashboard_snapshots

刷新后写入的版本聚合快照。

### refresh_jobs

刷新任务状态表，用于前端轮询。

## 10. Backend API

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/dashboard/versions` | 版本配置和元信息 |
| `GET` | `/api/dashboard/summary` | 当前版本 summary |
| `GET` | `/api/dashboard/version-comparison` | 趋势对比数据 |
| `GET` | `/api/dashboard/issues` | issue/scenario 明细分页 |
| `GET` | `/api/dashboard/issues/{issue_id}` | issue 详情和相关 scenarios |
| `GET` | `/api/dashboard/scenarios/{scenario_id}` | scenario 跨版本结果 |
| `POST` | `/api/dashboard/refresh` | 创建刷新任务 |
| `GET` | `/api/dashboard/refresh/{job_id}` | 查询刷新任务状态 |
| `GET` | `/api/dashboard/root-causes` | 根因分布 |

`/api/dashboard/issues` 支持：

- `version`
- `root_cause`
- `trigger_type`
- `precision_label`
- `reproduced`
- `issue_id`
- `scenario_id`
- `page`
- `page_size`

## 11. Frontend 架构

```mermaid
flowchart TD
  App[App.tsx<br/>global state, routing, filters] --> TopControls
  App --> Overview
  App --> IssuesTable
  App --> IssueDetail
  App --> APIClient[api/client.ts]
  Overview --> Recharts
  IssuesTable --> TanStackTable[TanStack Table]
  IssueDetail --> APIClient
```

### App.tsx

职责：

- 页面切换：`overview` / `issues`。
- 全局状态：dark mode、language、sidebar collapsed。
- 拉取 versions、summary、comparison、issues。
- 统一处理首页卡片到 issue 明细页的 drill-down。
- 处理版本筛选、平台筛选、大版本筛选、测试版本筛选。

### Overview.tsx

首页总览：

- KPI cards。
- 版本准召趋势折线图。
- 复现拆分柱状图。
- Source GT / Sim Estimate 表。
- 当前版本 root cause 分布。

趋势图交互：

- `精确率 / 召回率 / F1` 可手动开关。
- `显示数值 / 隐藏数值` 控制折线点百分比标签。
- 折线图和柱状图不跳转 issue，避免误操作。

### IssuesTable.tsx

Scenario 级明细表：

- 查询框支持 issue id 或 scenario id。
- 支持 version、root cause、trigger type、TP/FP/FN/TN 筛选。
- 当前选中结果以 `scenario_id + version_key` 定位，避免同 issue 多 scenario 混淆。

### IssueDetail.tsx

右侧详情面板：

- 拉取 `/dashboard/scenarios/{scenario_id}`。
- 如果有 issue id，再拉取 `/dashboard/issues/{issue_id}`。
- 展示当前 scenario、job id、dataset role、trigger value、source labels、同场景跨版本结果、同 issue 其他场景。

### i18n

`i18n.ts` 内置 zh/en 两套文案，语言偏好写入 `localStorage.lang`。

### Theme

主题状态写入 `localStorage.theme`。暗色模式使用同一蓝色风格，不切换到大面积紫色或灰黑风格。

## 12. 部署与运行

### Docker Compose

```bash
cd ra_sim_repro_dashboard
docker compose up --build
```

服务：

- Frontend: `http://127.0.0.1:5174`
- Backend: `http://127.0.0.1:8000`
- PostgreSQL: host `5433`, container `5432`
- Redis: host `6380`, container `6379`

### 环境变量

```bash
DATABASE_URL=postgresql+psycopg2://ra_dashboard:ra_dashboard@postgres:5432/ra_dashboard
REDIS_URL=redis://redis:6379/0
ENABLE_RQ=1
VERSIONS_CONFIG=/app/config/versions.yaml
MOCK_DATA_DIR=/app/data/mock

VOYAGER_RESULT_BASE_URL=https://voyager.intra.xiaojukeji.com
VOYAGER_COOKIE=
TRAIL_BASE_URL=http://100.69.238.11:8000/voyager/trail
TRAIL_APP_ID=
TRAIL_APP_TOKEN=
SCENARIO_APP_ID=
SCENARIO_APP_TOKEN=
ISSUE_APP_ID=
ISSUE_APP_TOKEN=
```

不要提交真实 token、cookie 或 `.env`。

## 13. 本地开发

### Backend

```bash
cd ra_sim_repro_dashboard/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd ra_sim_repro_dashboard/frontend
npm install
npm run dev
```

## 14. 测试与检查

Frontend:

```bash
cd ra_sim_repro_dashboard/frontend
npm run build
```

Backend:

```bash
cd ra_sim_repro_dashboard/backend
pytest tests
```

如果本机没有 Python 测试依赖，可以用 Docker 镜像挂载 tests：

```bash
docker compose -f ra_sim_repro_dashboard/docker-compose.yml run --rm --no-deps \
  -v /home/didi/workspace/ra_tools/ra_sim_repro_dashboard/backend/tests:/app/backend/tests:ro \
  backend pytest tests
```

## 15. 故障排查

### 页面暂无看板数据

检查：

1. `GET /api/dashboard/summary` 是否 404。
2. 是否已经执行过 `POST /api/dashboard/refresh`。
3. `config/versions.yaml` 是否包含 current version。
4. Postgres 中是否有 `scenario_version_results`。

### 刷新任务一直 queued

检查：

1. `worker` 容器是否启动。
2. Redis 是否可用。
3. `ENABLE_RQ` 是否为 `1`。
4. 如果 RQ 入队失败，后端会降级 background task，并在 job message 中记录原因。

### 真实 API 不可用

检查：

1. `TRAIL_APP_ID` / `TRAIL_APP_TOKEN` 是否配置。
2. `SCENARIO_APP_ID` / `SCENARIO_APP_TOKEN` 是否配置，未配置时默认复用 Trail。
3. 内网域名或 VIP 是否可访问。
4. 后端日志中是否出现 API fallback warning。

### 指标和表格不一致

检查：

1. `source_gt.data_source` 是 `scenario_api` 还是 `config_fallback`。
2. `sim_estimate.data_source` 是 `query_report` 还是 fallback。
3. 正负样本 job id 是否配反。
4. Scenario labels 是否和 release binary 对应。

## 16. 设计取舍

- 使用配置驱动版本，不把 release 版本写死在代码里。
- 使用快照 API 支撑首页，避免前端重复聚合明细。
- 明细表按 scenario-version 展示，不按 issue 聚合，避免一个 issue 下多个 scenario 混在一起。
- Source GT 和 sim estimate 同时保留，便于定位是源场景挖掘差异还是仿真复现差异。
- 后端对内部 API 做 fallback，保证看板可启动、可展示最近一次有效数据。

## 17. 后续扩展

- 增加 Alembic migration 管理数据库结构变更。
- 增加 API contract tests，覆盖 `/summary`、`/issues`、`/scenarios`。
- 对 issue 明细增加 scenario timeline 或 bag frame 入口。
- 支持多 config profile，比如 Q2 release、Q3 release、实验版本。
- 为 refresh job 增加 per-version 进度和 warning 明细表。
