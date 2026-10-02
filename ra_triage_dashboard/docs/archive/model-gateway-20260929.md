# 模型网关排查 · 2026-09-29

> 历史归档：记录 2026-09-29 至 2026-09-30 的排查和恢复过程，2026-10-02 整理归档。
> 文内“当前”、PID、端口、模型列表及配置状态均指对应记录时刻，不代表现状。后续凭据接入已覆盖早期“尚未配置”的结论；复用操作前应重新核实目标环境。
> 原始位置：`reports/assignment_ui_20260929/model-status.md`。以下原始记录完整保留。

## 凭据接入 · 2026-09-30 00:45

- 按用户要求，将 8786 的 `DASHBOARD_RA_MODEL_API_KEY_FILE` 从 `/dev/null` 改为服务器既有 `0600` 同账户密钥文件引用，未复制或输出密钥。
- 已备份配置并重启 `ra_triage_dashboard_8786_dev`；`/health` 显示 `model_gateway.configured=true`。
- 单人分配实测：`source=llm`，名称 `0508 Case标注 1071 Case 单人`，HTTP 200，0.728 秒。
- 双人场景的一次模型建议为 `0508 Case标注 1071Case 2人单人`，缺少要求的 `2人均分`，因此规则回退仍可能出现；这是名称校验机制，不代表凭据未配置。
- 8786 外部写入开关仍关闭，8785 正常且版本未变。
- 服务器回滚记录：`model-credential-20260930T004517/service_env.before.json`（位于既有 8786 experiment root）。

## 后续恢复结果 · 2026-09-29 21:41

用户明确要求单卡重启后，已在 Luban GPU 1 成功启动 Qwen3.8-27B：

- 模型 PID `3154532`，端口 `8012`，单卡 H20，显存约 72,758 MiB。
- `CUDA_VISIBLE_DEVICES=1`，GPU 0 原任务仍在运行。
- 后端推理 HTTP 200，回复 `OK`，0.44 秒；正式网关推理 HTTP 200，回复 `OK`，0.385 秒。
- LiteLLM 已重新扫描并重启，PID `3167333`。当前目录仅含存活的 Qwen3.8-27B/Qwen3.8-27B 与 RO-RA/ro-ra-1024_3-ckpt350；失效的 RA-Triage 条目已由扫描移除。
- 当前日志：`/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/qwen38-name-service/vllm-20260929T212655.log`。
- PID/日志指针：同目录 `vllm.pid` / `current_log`。
- 包装脚本会把未知参数后独立的值误认作位置参数；透传参数必须使用 `--max-num-seqs=1`、`--max-num-batched-tokens=32768`、`--reasoning-parser=qwen3`。
- 8786 凭据配置未修改，命名仍会走规则，直到单独配置服务器凭据文件。

## 初始排查（恢复前）

- `https://ra-model.intra.xiaojukeji.com/v1/models` 无凭据为 HTTP 401；使用服务器既有凭据为 HTTP 200，约 82 ms。列表速度不代表推理速度。
- 网关当前列出 `RO-RA/ro-ra-1024_3-ckpt350`、`RA-Triage/original330`、`RA-Triage/h2`。
- RO-RA 的 `10.152.16.59:8013/v1/models` 可达；通过正式域名进行实际推理返回 HTTP 200，耗时 7.84 秒，正常结束（stop）。
- 两个 RA-Triage 条目都依赖 Luban `8014`，目前连接拒绝，是过期列表条目。
- 命名使用 `Qwen3.8-27B/Qwen3.8-27B`，不在列表中，网关推理请求 HTTP 400（约 73 ms）；Luban 的 `8012` 未监听。
- 8786 `/health` 的 `model_gateway.configured=false`。因此页面当前显示的是规则生成名称，即使模型恢复，8786 仍需配置服务器凭据文件才能使用模型。
- Luban 上 LiteLLM 的 `80` 端口正常。其他配置的 8008/8009/8010/8011 后端均未监听。

## 已定位的启动资源

- SSH：Mac/T3650 使用 `ssh luban_new`；cloud 必须经过 T3650，使用 host-ops `hop.sh luban_new`。
- Conda：`source ~/.zshrc && init_vlm`，现有 `vlm` 环境。
- 启动脚本：`/home/luban/stuck_auto_triage_vlm/scripts/07_vllm_serve.py`。
- 权重：`/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/.cache/modelscope/Qwen/Qwen3.8-27B`，已确认 `config.json` 存在。
- 旧日志：`/tmp/ra_qwen38_27b_v33_lubannew_8012.log`；旧实例使用 vLLM 0.19.1，单卡 H20、BF16、32768 上下文、80% 显存。
- 排查时 GPU 0 已占约 63 GB，GPU 1 空闲；启动前必须重新检查。旧日志末尾存在 `No space left on device`，不能仅据此确定停机原因。当前容器盘剩余约 1.9 GB，NFS 剩余约 4.2 TB。

## 已使用的启动命令

在 `luban_new` 上执行，先确认 GPU 1 仍空闲且 8012 未占用：

```bash
source ~/.zshrc
init_vlm
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv
ss -tlnp | grep ':8012 '

model_ops_dir=/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/qwen38-name-service
mkdir -p "$model_ops_dir"
export VLLM_NO_USAGE_STATS=1
nohup python /home/luban/stuck_auto_triage_vlm/scripts/07_vllm_serve.py \
  --model /nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/.cache/modelscope/Qwen/Qwen3.8-27B \
  --gpus 1 --tp 1 --port 8012 \
  --served-model-name qwen38-27b-v33-lubannew \
  --max-model-len 32768 --gpu-memory-utilization 0.8 \
  --max-pixels 602112 --max-num-seqs=1 \
  --max-num-batched-tokens=32768 --disable-custom-all-reduce \
  --reasoning-parser=qwen3 \
  > "$model_ops_dir/vllm.log" 2>&1 < /dev/null &
```

脚本已包含关闭 thinking、BF16、Triton GDN 和 pyarrow 预导入。启动完成后先检查 `/v1/models` 和一次实际推理，再更新网关：

```bash
curl -fsS http://127.0.0.1:8012/v1/models
curl -fsS http://127.0.0.1:8012/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen38-27b-v33-lubannew","messages":[{"role":"user","content":"只回复 OK"}],"max_tokens":16,"stream":false}'
cd /home/luban/workspace/litellm-gateway
python scripts/scan_and_generate.py --restart
```

`endpoints.yaml` 已含 8012 及 `public_name: Qwen3.8-27B`，扫描后会恢复公开别名 `Qwen3.8-27B/Qwen3.8-27B`，并移除未存活的旧模型条目。此次已完成扫描和网关重启，验证结果见顶部恢复记录。

最后在 8786 配置 `DASHBOARD_RA_MODEL_API_KEY_FILE` 指向既有、服务账户拥有且权限为 `0600` 的服务器密钥文件，按既有 Supervisor 流程重启隔离服务，并验证名称接口返回 `source=llm`。不要把密钥放进浏览器、命令行或源码。模型返回的名称如果未通过关键字段校验，仍会回退 `source=rule`。
