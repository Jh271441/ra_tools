# Gateway Route Plan

Last updated: 2026-07-13

## Summary

- `/` 改为静态工具聚合首页。
- `model_release_pipeline` 迁到 `/release/`（前端需改 `base=/release/`）。
- RA 仿真复现看板接入 `/sim/`，前端改 `base=/sim/` + history route，支持浏览器/鼠标前进后退。
- CPA 低优先级接入 `/cpa/` 和 `/cpa/v1/`，做成可整段删除的独立配置块。
- **本期不做上游服务改绑 127.0.0.1**：各服务继续监听 0.0.0.0，同事可端口直连，网关只做统一入口，不做访问收敛（见 Deferred）。

## Implementation Status

当前 worktree 已经实施本计划，并已在本机 gateway 上完成 smoke 验收：

- `ops/gateway/nginx.conf` 已新增 `/release/`、`/sim/`、`/sim/api/`、`/cpa/`、`/cpa/v1/` 和静态 portal 首页。
- `ops/gateway/docker-compose.yml` 已挂载 `ops/gateway/portal` 到 `/usr/share/nginx/portal`，并挂载 `ra_sim_repro_dashboard/frontend/dist` 到 `/usr/share/nginx/sim`。
- `/v1/`、`/dcc/`、`/tb/` 保持既有语义。
- `/cpa/v1/` 已按低优先级实验块处理，nginx 不额外校验 CPA token，并关闭 SSE buffering。
- CPA management UI 不完全支持 `/cpa/` 子路径：页面会从根路径请求 `/v0/management/*`。Gateway 已增加窄范围兼容路由 `/v0/management` / `/v0/management/` 透传到 CPA，避免把整个 `/v0/` 暴露给 CPA。
- CPA management UI 的默认连接地址只保留 scheme/host/port，因此“可用模型列表”还会请求根路径 `/v1/models`。Gateway 对这个精确路径按 CPA management 页 Referer 分流到 CPA；其他客户端访问 `/v1/models` 时仍走 lingma-proxy 并执行原有鉴权。

前端改造状态：

- model release 前端已改为 `base: '/release/'`，API base 跟随 Vite base 走 `/release/api`。
- `model_release_pipeline/web_app.py` 已兼容直连 `:8765` 时的 `/release/...` 前缀路径。
- RA 看板前端已改为 `base: '/sim/'`，API base 跟随 Vite base 走 `/sim/api`。
- RA 看板 `App.tsx` 已增加轻量 history route，支持 `/sim/overview`、`/sim/issues`、`/sim/status`。

- 已重新 build `model_release_pipeline/web_frontend` 和 `ra_sim_repro_dashboard/frontend`。
- 已 `docker compose -f ops/gateway/docker-compose.yml up -d` recreate gateway，使新增 portal/sim bind mount 生效。
- 已通过 `nginx -t` 和下方 Test Plan 的主要 HTTP / browser history 验收。

## Phase 1 — Portal + /release/（已实施并验收）

1. 新增静态聚合首页，由 nginx 直接托管，`/` 不再代理 8765。首页不依赖任何后端 API，入口卡片：Release Tools、RA Sim Repro、DCC、TensorBoard、CPA Management。
2. model release 前端改造：
   - `base: '/release/'`；
   - API 请求走 `/release/api`（或相对路径），不再请求根路径 `/api`；
   - 重新 build。
3. nginx 新增：
   - `location = /release { return 301 /release/; }`
   - `location /release/ { proxy_pass http://127.0.0.1:8765/; }`
4. `/v1/`、`/dcc/`、`/tb/` 保持现状不动。

## Phase 2 — RA 看板 /sim/（已实施并验收）

前端改造（接入前必须完成）：

1. Vite `base: '/sim/'`。
2. API base 支持 `/sim/api`（开发态仍可用 `/api` 代理到 8000）。
3. 轻量 history route：
   - 模块切换时 `pushState` 到 `/sim/overview` / `/sim/issues` / `/sim/status`；
   - 监听 `popstate` 还原页面状态；
   - 直接打开 `/sim/issues` 能进入对应模块。
   - 效果：鼠标侧键前进/后退在点过的模块间切换，而不是退出网页。

nginx 接入（推荐静态托管，而非代理 Vite dev server）：

- `vite build` 产物由 nginx `alias` 托管 `/sim/`，并配 `try_files $uri /sim/index.html;` 兜底 history route（解决 `/sim/issues` 刷新 404）。
- `location /sim/api/ { proxy_pass http://127.0.0.1:8000/api/; }`
- `location = /sim { return 301 /sim/; }`
- 过渡方案（可选）：`/sim/` 暂时代理 `127.0.0.1:5174`，但需给 Vite dev server 配 `allowedHosts` 和 HMR websocket；dev 进程挂掉入口即 502，不作为给同事的长期入口。

## Phase 3 — CPA（已实施并完成基础验收，低优先级，可拆卸）

CPA 可能不长久，验收失败不阻塞 Phase 1/2。配置要求：

1. `/cpa/`、`/cpa/v1/` 写成一段独立、注释边界清晰的配置块，CPA 下线时整段删除即可。
2. `/cpa/v1/` 纯透传到 `127.0.0.1:8317/v1/`：
   - 不在 nginx 层加 token 校验，`Authorization: Bearer sk-cpa-...` 由 CPA 自己校验，nginx 原样转发；
   - 模型接口是流式 SSE，必须 `proxy_buffering off; proxy_cache off; chunked_transfer_encoding on;`（同现有 `/v1/`）。
3. `/cpa/` 指向 CPA management UI，默认落到 `/cpa/management.html#/quota`。
4. `location = /cpa { return 301 /cpa/; }`
5. CPA management UI 会硬编码请求根路径 `/v0/management/*`，因此额外保留窄范围兼容路由：
   - `location = /v0/management { proxy_pass http://127.0.0.1:8317; }`
   - `location /v0/management/ { proxy_pass http://127.0.0.1:8317; }`
   - 不要扩大为整个 `/v0/`，避免污染 gateway 根命名空间。
6. CPA management UI 的模型发现请求同样不完全支持子路径：
   - 默认连接地址由浏览器的 scheme/host/port 生成，不包含 `/cpa`，因此页面请求根 `/v1/models`；
   - `location = /v1/models` 仅在 Referer 来自同一 gateway 的 `/cpa/` 页面时转发 CPA `127.0.0.1:8317/v1/models`；
   - 无 CPA Referer 时仍要求 lingma token，并转发 `127.0.0.1:8095/v1/models`，不能把根 `/v1/models` 全局改给 CPA；
   - 用户手动把“自定义连接地址”设成 `http(s)://<gateway-host>/cpa` 也能工作，但不作为每个浏览器都要执行的部署步骤。

## Target Routes

| Route | Target | 说明 |
| --- | --- | --- |
| `/` | nginx 静态聚合页 | 无后端依赖 |
| `/release/` | `127.0.0.1:8765` | 前端需 `base=/release/` |
| `/sim/` | 静态 build 产物（过渡期 `127.0.0.1:5174`） | history route 需 `try_files` 兜底 |
| `/sim/api/` | `127.0.0.1:8000/api/` | |
| `/cpa/` | CPA management UI | 独立块，可整段删除 |
| `/cpa/v1/` | `127.0.0.1:8317/v1/` | 纯透传 + SSE 关缓冲 |
| `/v0/management/` | `127.0.0.1:8317/v0/management/` | CPA management UI 兼容路由 |
| `/v1/models` | CPA 或 lingma-proxy | CPA management Referer → CPA；其他请求保持 lingma 鉴权 |
| `/v1/` | `127.0.0.1:8095/v1/` | 保持 lingma-proxy + Bearer 校验 |
| `/dcc/` | `127.0.0.1:9999` | 保持不变 |
| `/tb/` | `127.0.0.1:16006` | 保持不变 |

通用规则：所有新前缀（`/release`、`/sim`、`/cpa`）都要加无斜杠 301 补齐，与现有 `/dcc`、`/tb` 一致。

## Deferred — 上游改绑 127.0.0.1（本期不做）

当前 8765 / 5174 / 8000 / 9999 / 16006 / 8317 均监听 0.0.0.0，同事可绕过网关端口直连。本期为保证大家先能访问，**明确不做**改绑收敛。

后果与边界（记录在案）：

- nginx 层的任何校验（如 `/v1/` Bearer）对端口直连无效；
- 8000 / 8765 / 5174 无自身鉴权，内网可直接访问；CPA 8317 自带 token 校验，风险较低；
- 后续若要做访问收敛，再把各服务改绑 `127.0.0.1` 并以网关为唯一入口，届时此段升级为正式 Phase。

## Test Plan

1. `nginx -t` 后 reload gateway。
2. `http://127.0.0.1/` 返回静态聚合页（不依赖任何后端进程）。
3. `http://127.0.0.1/release/` 页面与资产正常加载（无 `/assets/` 404）。
4. `http://127.0.0.1/sim/` 正常打开总览。
5. `http://127.0.0.1/sim/issues` 直接打开与刷新均正常（history 兜底生效）。
6. RA 页面内切换模块后，鼠标/浏览器前进后退在总览与 Issue 明细间切换，不退出网页。
7. `http://127.0.0.1/sim/api/dashboard/summary` 返回 JSON。
8. `http://127.0.0.1/cpa/` 打开 management UI。
9. `curl http://127.0.0.1/cpa/v1/models -H "Authorization: Bearer <cpa-token>"` 返回模型列表；无 token 时由 CPA 返回 401。
10. 模拟 CPA management UI 请求根模型接口：带 CPA token 和 `Referer: http://127.0.0.1/cpa/management.html` 的 `GET /v1/models` 返回模型列表。
11. 同一个 `GET /v1/models` 去掉 CPA Referer 后仍按 lingma 规则鉴权，CPA token 不能把普通根 `/v1/` 请求导向 CPA。
12. CPA 进程停掉时，`/`、`/release/`、`/sim/` 不受影响。

## Validation Results（2026-07-09）

- `docker compose -f ops/gateway/docker-compose.yml config` 通过。
- `docker compose -f ops/gateway/docker-compose.yml exec nginx nginx -t` 通过。
- Gateway nginx 已 recreate，确认挂载：
  - `ops/gateway/portal` → `/usr/share/nginx/portal`
  - `ra_sim_repro_dashboard/frontend/dist` → `/usr/share/nginx/sim`
- `GET /` → `200 text/html`，返回静态聚合页。
- `GET /release/` → `200 text/html`，HTML 资产路径为 `/release/assets/...`。
- `GET /release/api/runs` → `200 application/json`。
- `GET /sim/` → `200 text/html`，HTML 资产路径为 `/sim/assets/...`。
- `GET /sim/issues` → `200 text/html`，history route 直接打开可由 SPA 兜底。
- `GET /sim/api/dashboard/summary` → `200 application/json`。
- `GET /cpa/` → `302 /cpa/management.html#/quota`。
- `GET /cpa/v1/models` 无 token → CPA 返回 `401 application/json`，说明 nginx 已透传到 CPA。
- `GET /v0/management/config` 无 management key → CPA 返回 `401 {"error":"missing management key"}`，说明 management UI 的绝对路径 API 已透传到 CPA，不再由 gateway portal 返回 404。
- Headless Chrome 验证：`/sim/overview -> /sim/issues -> history.back() -> /sim/overview -> history.forward() -> /sim/issues`。

Python 单测未跑通：系统 Python 和项目 `.venv` 都没有安装 `pytest`。本轮已用前端 production build、nginx 配置检查、HTTP smoke 和浏览器 history 验证覆盖 gateway 接入风险。

## Assumptions

- `/release/` 作为 model release tools 推荐路径，旧的根路径入口在 Phase 1 后废弃。
- `/sim/` 目标态为静态托管；代理 5174 仅作过渡。
- CPA 不稳定，验收失败不阻塞其他路由；配置块和 `/v0/management/*` 兼容路由随时可整段删除。
- 根 `/v1/` 不动，继续给 lingma-proxy 使用。
- 本期不做 0.0.0.0 → 127.0.0.1 改绑（见 Deferred）。
