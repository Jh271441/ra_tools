# RA Sim Repro Dashboard

RA stuck 自触发模型仿真复现看板。该应用是 `ra_sim_repro_dashboard/` 下的独立系统，和既有 `model_release_pipeline` 没有运行时依赖。

完整架构设计见 [ARCHITECTURE.md](ARCHITECTURE.md)。本文档作为项目 README，覆盖目标、系统边界、运行方式、真实数据接入、API 和排障入口。

## 1. 看板目标

看板用于把 release 版本的 source scenario 与仿真 job 结果对齐，回答三个问题：

- 当前版本的仿真复现率是多少。
- 当前版本跑前序版本场景集后，Precision / Recall / F1 趋势是否合理。
- 每一个 issue / scenario 为什么是 TP、FP、FN、TN，以及它在不同版本上的仿真触发表现。

核心指标：

```text
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
f1        = 2 * precision * recall / (precision + recall)

sim_repro_rate = sim-triggered source auto-trigger scenarios
               / source auto-trigger scenarios

source auto-trigger scenarios = positive_auto + negative_auto
positive_manual only participates in recall / FN estimation, not sim_repro_rate.
```

## 2. 系统边界

本项目负责：

- 读取 `config/versions.yaml` 中配置的 release、binary、scenario labels、positive / negative sim jobs。
- 通过后端拉取 Scenario API、Voyager / Trail sim result API 和 issue metadata。
- 归一化每个 scenario 的 source GT 与仿真触发信号。
- 计算版本聚合指标和 scenario-version 明细。
- 提供 React 看板、版本筛选、趋势图、root cause 分布和 issue 明细面板。

本项目暂不负责：

- 复用或改造 `model_release_pipeline`。
- 前端直接访问内网 API 或保存 token。
- bag frame timeline 级解析。
- 自动创建仿真 job。当前版本只消费人工提供的 positive / negative job id。

## 3. 技术栈

| 层 | 技术 | 说明 |
| --- | --- | --- |
| Frontend | React, Vite, TypeScript | 单页看板，开发端口 `5174` |
| UI | Tailwind CSS, local shadcn-style components | Apple-like 蓝色风格，支持明暗模式 |
| Charts | Recharts | 折线图、柱状图、tooltip、数据标签 |
| Table | TanStack Table | issue / scenario 明细 |
| i18n | i18next, react-i18next | 中文 / 英文切换 |
| Backend | FastAPI, Pydantic, SQLAlchemy | API、刷新任务、数据归一化 |
| DB | PostgreSQL / SQLite | Docker 默认 PostgreSQL，本地可用 SQLite |
| Queue | Redis, RQ | 异步刷新与刷新锁 |
| Deployment | Docker Compose | frontend、backend、worker、postgres、redis |

## 4. 运行时架构

```mermaid
flowchart LR
  Browser[Browser] --> Frontend[React Frontend<br/>:5174]
  Frontend -->|/api/dashboard/*| Backend[FastAPI Backend<br/>:8000]
  Backend --> DB[(PostgreSQL / SQLite)]
  Backend --> Redis[(Redis)]
  Backend -->|enqueue refresh| Worker[RQ Worker]
  Worker --> DB
  Worker --> Redis
  Worker --> ScenarioAPI[Scenario API]
  Worker --> SimAPI[Voyager / Trail query_report]
  Worker --> IssueAPI[Issue API]
  Worker --> Mock[Mock JSON]
  Backend --> Config[config/versions.yaml]
  Worker --> Config
```

职责划分：

- Frontend: 展示、筛选、交互，不保存内部 API 凭据。
- Backend: 提供 REST API、创建刷新任务、读取快照和明细。
- Worker: 执行真实刷新，调用内部 API，计算指标，写数据库。
- PostgreSQL: 存储版本、scenario、issue、scenario-version result、dashboard snapshot、refresh job。
- Redis: RQ 队列和同配置刷新互斥锁。

## 5. 数据链路

```mermaid
sequenceDiagram
  participant FE as Frontend
  participant API as Backend API
  participant W as Worker
  participant S as Scenario API
  participant V as Voyager / Trail
  participant I as Issue API
  participant DB as Database

  FE->>API: POST /api/dashboard/refresh
  API->>DB: create RefreshJob
  API->>W: enqueue
  W->>DB: sync versions from config
  W->>S: query scenarios by source labels
  W->>V: query positive and negative sim jobs
  W->>I: query issue metadata
  W->>DB: upsert scenarios, issues, scenario-version results
  W->>DB: write dashboard snapshot
  FE->>API: poll refresh status and reload dashboard data
```

数据优先级：

1. Mock JSON: `data/mock/sim_job_{job_id}.json` 和 `data/mock/issues.json`。
2. Voyager `query_report`: 依赖 `VOYAGER_COOKIE`。
3. Trail signed API: 依赖 `TRAIL_APP_ID` / `TRAIL_APP_TOKEN`。
4. Config fallback: 内部 API 不可用时使用 `source_gt_counts` / `sim_eval` 保证看板可启动。

## 6. 版本配置

版本配置在 [config/versions.yaml](config/versions.yaml)。当前已配置四个 release：

| Version | Positive Job | Negative Job | Source TP | Source FN | Source FP |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gen4-release-20260327` | `39467349` | `39467345` | 438 | 229 | 284 |
| `gen4-release-20260403` | `39467411` | `39467401` | 570 | 302 | 269 |
| `gen4-release-20260410` | `39467433` | `39467427` | 696 | 293 | 354 |
| `gen4-release-20260417` | `39467319` | `39367009` | 582 | 254 | 359 |

单版本结构示例：

```yaml
versions:
  "gen4-release-20260417":
    label: "release20260417"
    binary: "gen4-release-20260417"
    binary_id: 1616813
    commit: "2e2ac367c9d1355fb10c4462d95a3f70c939d052"
    sim_plan: "lxh_ra_stuck_release_20260417-openloop"
    sim_jobs:
      positive_job_id: 39467319
      negative_job_id: 39367009
    scenario_sets:
      positive:
        labels:
          - "lxh_ra_stuck_20260425_pos"
          - "lxh_ra_stuck_20260425_AutoTrigger"
          - "lxh_ra_stuck_20260425_gen4-release-20260417"
        manual_labels:
          - "lxh_ra_stuck_20260425_pos"
          - "lxh_ra_stuck_20260425_ManualTrigger"
          - "lxh_ra_stuck_20260425_gen4-release-20260417"
      negative:
        labels:
          - "lxh_ra_stuck_20260425_neg"
          - "lxh_ra_stuck_20260425_AutoTrigger"
          - "lxh_ra_stuck_20260425_gen4-release-20260417"
        normal_stop_labels:
          - "lxh_ra_stuck_20260425_gen4-release-20260417"
          - "lxh_ra_stuck_20260425_neg"
          - "lxh_ra_stuck_20260425_normal_stop"
    source_gt_counts:
      auto_trigger_tp: 582
      manual_trigger_fn: 254
      auto_trigger_fp: 359
```

## 7. 仿真判定

positive job 对应 source road-positive 场景：

- `Base.dpe_assist_channel_triggered.value >= 1`: TP。
- `Base.dpe_assist_channel_triggered.value < 1`: FN。

negative job 对应 source road-negative 场景：

- `Base.dpe_assist_channel_triggered.value >= 1`: FP。
- `Base.dpe_assist_channel_triggered.value < 1`: TN。

后端归一化字段为 `dpe_assist_channel_triggered`。`0` 和 `false` 是有效值，不能被 truthy fallback 覆盖。

## 8. 目录结构

```text
ra_sim_repro_dashboard/
  README.md
  ARCHITECTURE.md
  docker-compose.yml
  .env.example
  config/
    versions.yaml
    versions.example.yaml
  data/mock/
    issues.json
    sim_job_*.json
  backend/
    app/
      api/routes.py
      config.py
      database.py
      metrics.py
      models.py
      schemas.py
      worker.py
      services/
    tests/
  frontend/
    src/
      App.tsx
      api/client.ts
      components/
      i18n.ts
      types.ts
```

## 9. Backend API

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/dashboard/versions` | 版本配置和元信息 |
| `GET` | `/api/dashboard/summary` | 当前版本 summary |
| `GET` | `/api/dashboard/version-comparison` | 版本趋势数据 |
| `GET` | `/api/dashboard/issues` | issue/scenario 明细分页 |
| `GET` | `/api/dashboard/issues/{issue_id}` | issue 详情 |
| `GET` | `/api/dashboard/scenarios/{scenario_id}` | scenario 跨版本结果 |
| `POST` | `/api/dashboard/refresh` | 创建刷新任务 |
| `GET` | `/api/dashboard/refresh/{job_id}` | 查询刷新任务 |
| `GET` | `/api/dashboard/root-causes` | 根因分布 |

## 10. 本地运行

Backend:

```bash
cd ra_sim_repro_dashboard/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd ra_sim_repro_dashboard/frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5174`，首次进入后点击刷新。默认配置会优先读取 `data/mock` 中的 mock 数据。

## 11. Docker Compose

```bash
cd ra_sim_repro_dashboard
docker compose up --build
```

服务端口：

- Frontend: `http://127.0.0.1:5174`
- Backend API: `http://127.0.0.1:8000`
- PostgreSQL host port: `5433`
- Redis host port: `6380`

## 12. 真实数据接入

复制环境变量模板：

```bash
cd ra_sim_repro_dashboard
cp .env.example .env
```

按需填写：

```bash
VOYAGER_RESULT_BASE_URL=https://voyager.intra.xiaojukeji.com
VOYAGER_COOKIE='copy Cookie header from Chrome DevTools'
VOYAGER_QUERY_PAGE_SIZE=1000

TRAIL_BASE_URL=http://100.69.238.11:8000/voyager/trail
TRAIL_APP_ID=...
TRAIL_APP_TOKEN=...

SCENARIO_APP_ID=...
SCENARIO_APP_TOKEN=...
ISSUE_APP_ID=...
ISSUE_APP_TOKEN=...
```

不要提交真实 cookie、token、个人登录态或 `.env`。

## 13. 测试

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

如果本机没有 Python 测试依赖，可以用 Docker 镜像运行后端测试：

```bash
docker compose -f ra_sim_repro_dashboard/docker-compose.yml run --rm --no-deps \
  -v /home/didi/workspace/ra_tools/ra_sim_repro_dashboard/backend/tests:/app/backend/tests:ro \
  backend pytest tests
```

## 14. 排障入口

页面无数据：

- 检查是否执行过 `POST /api/dashboard/refresh`。
- 检查 `GET /api/dashboard/summary` 是否返回 404。
- 检查 `config/versions.yaml` 是否包含 current version。
- 检查数据库是否已有 `scenario_version_results`。

真实 API 不可用：

- 检查内网是否可访问。
- 检查 `VOYAGER_COOKIE`、`TRAIL_APP_ID`、`TRAIL_APP_TOKEN`、`SCENARIO_APP_ID`、`SCENARIO_APP_TOKEN`。
- 检查后端日志中是否出现 fallback warning。
- 确认 `data/mock` 是否存在同 job id 的 mock 文件，mock 会优先覆盖真实 API。

指标和表格不一致：

- 确认 positive / negative job id 没有配反。
- 确认 scenario labels 和 release binary 对应。
- 对比 `source_gt.data_source` 是 `scenario_api` 还是 `config_fallback`。
- 对比 `sim_estimate.data_source` 是 `query_report` 还是 fallback。

## 15. 进一步文档

- [ARCHITECTURE.md](ARCHITECTURE.md): 完整架构、数据模型、刷新链路、前端模块和扩展计划。
- [config/versions.example.yaml](config/versions.example.yaml): 新版本配置模板。
- [docker-compose.yml](docker-compose.yml): 本地完整服务编排。
