# Auto Triage Bot MVP

独立、只读的 DChat 问答服务。它接收经过认证的 DChat 消息事件，从 RA Triage Workbench 的 loopback API 读取 Issue、不可变 baseline GT、默认或指定 Model Run，以及与该 Run 绑定的最新 Review，再调用内部 OpenAI-compatible 模型网关生成回复。

首版不会写 Review、Trail 或 GT，不会发布 AutoTriage 结果。D-Chat BotUser 要求回调在 5 秒内直接返回一条消息，因此服务先返回 `{"text":"收到，正在处理…"}`；看板查询和大模型调用在后台执行，完成后复用看板已经验证的 DChat BotUser `POST /v3/message.create` 回复到提问人的 LDAP 私聊。群聊中的即时确认会留在原会话，最终答案首版发私聊；若后续确认群内主动回复 API，再扩展为原会话回复。

## 跨机房中继架构

正式链路把接入面和数据面拆开，避免线上 DChat 主动访问线下 Cloud Server：

```text
DChat -> Kylin 永顺 /dchat -> Luban Relay (在线)
                                  ^
                                  | Cloud Server 主动 HTTPS pull/ack/nack
                                  |
Kylin 内蒙古 /dchat-worker <------+
Cloud Worker (线下) -> loopback Dashboard + model + DChat OpenAPI
```

- Kylin 会剥离公开前缀：`/dchat` 到 Relay `/`；`/dchat-worker/pull`、`/ack`、`/nack` 到 Relay 对应根路径。
- Relay 只保存标准化的 `event_id`、发送人、问题和可选 `chat_id`，不持有 Dashboard、模型或 DChat OpenAPI 凭据。
- Worker 使用单独的 `0600` Bearer token 主动拉取，任务采用超时租约、ACK/NACK、去重和最多 5 次退避重试。
- Relay 的 SQLite 必须位于 Luban 持久卷。`/dev/shm` 或容器根盘只允许临时联调，Pod 重建会丢失未完成任务。
- 回调 token 与 worker token 必须不同；任一 token 都不得放进 URL、仓库、进程参数或日志。

## 本地启动

默认是关闭状态和 loopback 投递，不会发送真实 DChat：

```bash
mkdir -p auto_triage_bot/.data
python3 -c 'from pathlib import Path; p=Path("auto_triage_bot/.data/webhook_secret"); p.write_text("local-test-secret", encoding="utf-8"); p.chmod(0o600)'
AUTOTRIAGE_BOT_ENABLED=true \
AUTOTRIAGE_BOT_ALLOWED_USERS='<your-ldap>' \
AUTOTRIAGE_BOT_DELIVERY_MODE=loopback \
AUTOTRIAGE_BOT_DASHBOARD_URL=http://127.0.0.1:8785 \
python3 -m uvicorn auto_triage_bot.main:app --host 127.0.0.1 --port 8790
```

Webhook HMAC 为 `hex(HMAC-SHA256(secret, body))`，放在 `X-DChat-Signature`。如果同时提供 `X-DChat-Timestamp`，签名内容是 `<timestamp>.<body>`，时间偏差不得超过 5 分钟。当前 BotUser 入门文档没有说明平台会附带签名头；生产接入可让受控网关校验来源后注入固定 `X-DChat-Signature`，并设置 `AUTOTRIAGE_BOT_WEBHOOK_AUTH_MODE=token`。不要把 token 放进 `notification_url` 查询参数。

标准化消息事件：

```json
{
  "event_id": "unique-message-id",
  "sender": {"username": "ldap"},
  "message": {"text": "请解释 Issue 12345678 为什么判错"},
  "chat_id": "optional-conversation-id"
}
```

URL 验证支持 `{"challenge":"..."}`，通过同一认证后原样返回 challenge。普通消息回调始终在 5 秒内返回合法的 BotUser 文本消息 JSON，而不是 `202 Accepted`。

## 模型与正式 DChat

模型和 DChat 凭据只从当前服务用户持有的 `0600` 文件读取：

```bash
export AUTOTRIAGE_BOT_MODEL_ID='<approved-model-id>'
export AUTOTRIAGE_BOT_MODEL_API_KEY_FILE='/restricted/model_gateway_api_key'
export AUTOTRIAGE_BOT_DCHAT_CREDENTIALS_FILE='/restricted/dchat_credentials.json'
export AUTOTRIAGE_BOT_DELIVERY_MODE=openapi
```

`dchat_credentials.json` 沿用看板格式：`client_id`、`client_secret`、数字 `bot_id`。模型 URL、DChat URL、Dashboard URL 都由服务端固定并校验允许主机，消息体不能指定 endpoint、key、路径或 Run 之外的服务器配置。

## DChat 开放平台需要做的操作

1. 可以复用现有发送通知的 DChat 应用，也可以新建独立的测试版工作台应用。复用时确认已有 BotUser 和主动发消息所需的 OpenAPI 权限；新建时需要重新申请。
2. 在应用详情右上角开启 **应用机器人（BotUser）** 形态。
3. 编辑 BotUser 形态，把 `notification_url` 填成网关暴露的 `/dchat`。该地址必须能被 D-Chat 服务器访问；不要填写本机的 `127.0.0.1:8790`。
4. Kylin 仅暴露公网前缀 `/dchat`，转发到独立的 `8790` 并剥离该前缀，和看板 `/manual` 的规则一致。公网 `/dchat`、`/dchat/smoke` 分别到达 8790 内部的 `/`、`/smoke`；这不会占用域名根目录或看板的 `8785`。
5. 在受控网关校验来源并注入固定验证 token，Bot 服务以当前服务用户持有的 `0600` 文件读取该 token。若联调发现 D-Chat 自带签名，再按真实 header/body 契约适配 `security.py`。
6. 安装测试版应用。用户私聊 BotUser、或在群聊中 @BotUser 时，D-Chat 会 POST 到 `notification_url`；服务必须在 5 秒内返回一条普通文本、带附件文本或交互消息。
7. 申请/确认后台完成答案所需的主动消息 OpenAPI 权限，并配置应用的 `client_id`、`client_secret`、数字 `bot_id` 到服务用户 `0600` 凭据文件。
8. 在灰度环境各测试一次私聊和群 @，保存脱敏后的真实 POST body/header 样例，用于核对 `events.py` 的发送人、消息文本和消息 ID 字段映射。
9. 先用测试 LDAP 验证即时确认、最终私聊、重复消息去重、看板链接、超时重试和限流；验证完成后再扩大群和用户范围。

已确认的 BotUser 契约：私聊 BotUser 和群聊 @BotUser 都会触发 `notification_url` POST，业务方需在 5 秒内直接返回一条消息；耗时任务可以先返回处理中消息，再通过 OpenAPI 通知结果。仍需用平台联调样例确认三项细节：入站签名/来源验证方式、POST 字段结构、群内主动回复 API。未确认前，正式模式只承诺“认证回调 + 即时确认 + LDAP 私聊最终答案”。

## Cloud Server 部署与连通性 smoke

Cloud Server 使用独立端口 `8790`，不复用或重启看板的 `8785`。`AUTOTRIAGE_BOT_BASE_PATH=/dchat` 声明公网前缀；Kylin 剥离前缀后，8790 内部接收 `/`、`/smoke` 和 `/health`。启动脚本默认只开放测试 LDAP、使用 loopback 投递，并启用无副作用的公网 `/dchat/smoke`：

```bash
bash auto_triage_bot/scripts/run_cloud_server.sh
```

部署后先验证：

```bash
bash auto_triage_bot/scripts/smoke.sh http://127.0.0.1:8790
```

公网 `/dchat/smoke` 只返回固定文本，不读取消息、看板或模型，也不发送 DChat。它用于验证 D-Chat 服务器能否访问部署地址；联通后再切换到经过认证的公网 `/dchat`。Kylin 不应暴露 8790 的任何其它前缀；公网/办公网入口必须由网关或防火墙限制来源，不能把未认证的事件处理接口直接暴露。

## 运行配置

| 变量 | 默认值/用途 |
|---|---|
| `AUTOTRIAGE_BOT_ENABLED` | `false`，fail-closed 总开关 |
| `AUTOTRIAGE_BOT_SMOKE_ENABLED` | `false`；临时启用无副作用连通性端点 |
| `AUTOTRIAGE_BOT_BASE_PATH` | `/dchat`；Kylin 对外暴露并剥离的非根前缀 |
| `AUTOTRIAGE_BOT_ALLOWED_USERS` | 逗号分隔 LDAP；启用时默认必须非空 |
| `AUTOTRIAGE_BOT_ALLOW_ALL_USERS` | `false`；全员开放必须显式设为 `true` |
| `AUTOTRIAGE_BOT_DATA_DIR` | `auto_triage_bot/.data` |
| `AUTOTRIAGE_BOT_WEBHOOK_AUTH_MODE` | `hmac`，可选 `token` |
| `AUTOTRIAGE_BOT_WEBHOOK_SECRET_FILE` | `<data_dir>/webhook_secret` |
| `AUTOTRIAGE_BOT_DASHBOARD_URL` | `http://127.0.0.1:8785`，只允许 loopback |
| `AUTOTRIAGE_BOT_DELIVERY_MODE` | `loopback`，正式为 `openapi` |
| `AUTOTRIAGE_BOT_MODEL_ID` | 空；为空时对 Issue 做事实摘录，不调用模型 |
| `AUTOTRIAGE_BOT_MODEL_API_KEY_FILE` | `<data_dir>/model_gateway_api_key` |
| `AUTOTRIAGE_BOT_DCHAT_CREDENTIALS_FILE` | `<data_dir>/dchat_credentials.json` |
| `AUTOTRIAGE_BOT_RELAY_URL` | `https://ra-model.intra.xiaojukeji.com/dchat-worker`；Cloud Worker 固定出口 |
| `AUTOTRIAGE_BOT_RELAY_WORKER_SECRET_FILE` | `<data_dir>/relay_worker_secret`；独立 `0600` token |
| `AUTOTRIAGE_BOT_RELAY_WORKER_ID` | `cloud-server-1` |
| `AUTOTRIAGE_BOT_RELAY_LEASE_SECONDS` | `120`；任务租约时间 |
| `AUTOTRIAGE_BOT_RELAY_MAX_ATTEMPTS` | `5`；最大交付尝试次数 |

事件状态保存在 `<data_dir>/bot_events.sqlite3`。`event_id` 唯一，进程重启会把中断的 `running` 事件恢复为 `queued`；临时失败指数退避，最多尝试 5 次。

## Luban Relay + Cloud Worker 启动

Luban 上先挂载一个持久化目录，并放入两个当前用户持有的 `0600` 文件：`webhook_secret` 是 Kylin 为 `/dchat` 注入的固定 token；`relay_worker_secret` 是只给 Cloud Worker 使用的独立随机 token。然后启动：

```bash
AUTOTRIAGE_BOT_DATA_DIR=/path/to/persistent/auto-triage-relay \
bash auto_triage_bot/scripts/run_luban_relay.sh
```

同一个 `relay_worker_secret` 通过受控凭据渠道写到 Cloud Server 的 `/volume/home/workspace/ra_triage_bot_data/relay_worker_secret`，权限设为 `0600`。Cloud Server 主动访问固定 HTTPS 地址并启动只读 worker：

```bash
bash auto_triage_bot/scripts/run_cloud_worker.sh
curl --noproxy '*' -fsS http://127.0.0.1:8790/health
```

先以 `AUTOTRIAGE_BOT_DELIVERY_MODE=loopback` 做队列 smoke；确认 callback → pull → ACK 后，再改成 `openapi` 做一个灰度 LDAP 的真实私聊。旧的 `auto_triage_bot.main:app` 直连进程保留为回滚入口，但不应与 remote worker 同时消费同一条回调。

## 测试

```bash
python3 -m unittest discover -s auto_triage_bot/tests -v
```

API 级测试还需要 Starlette 的测试依赖 `httpx`；缺少时该测试会明确 skip，其他单元测试仍会运行。
