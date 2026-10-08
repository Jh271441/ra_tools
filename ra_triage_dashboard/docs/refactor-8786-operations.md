# 8786 重构验收与发布命令

仅用于已经授权的8786隔离环境。使用`host-ops`选择SSH路由；不输出或传递URL文件内容。
现有8785发布继续使用`deploy_cloud.py`，不要用该脚本替代生产发布流程。

## 检查

- `python -m pytest ra_triage_dashboard/tests -q`：全量门禁。
- `python -m unittest discover -s ra_triage_dashboard/tests -p 'test_frontend_*contract.py'`：
  按领域分开的69项原源码契约检查，公共加载位于`frontend_contract_fixtures.py`。
- `test_assignment_components.py`、`test_assignment_creation_scope.py`：Node行为回归；
  源码契约检查不能代替交互测试。
- `test_deploy_8786.py`：归档SHA/路径、不可变源码、并发配置和回滚回归。
- `test_refactor_boundaries.py`：runtime无副作用导入、单连接初始化顺序和模块依赖边界。

## 冻结数据契约

先对当前8786数据库做pg_dump并恢复到独立`manual_refactor*`数据库，将其URL写入
同服务账号0600文件；不要让验收脚本指向生产库。保留dump和SHA以便重跑。

```sh
python scripts/capture_refactor_contract.py \
  --source-root /path/to/source/ra_triage_dashboard \
  --url-file /private/evidence/postgres_url \
  --env-file /private/config/service_env.json \
  --output /private/evidence/before.json.gz
```

以旧/新源码各跑一次，解压JSON逐字节比较。覆盖所有数据集标注投影/裁决筛选/GT候选、
批次与完成/未完成明细、Run集合/评估，以及OpenAPI。脚本强制只读连接，不初始化schema。
数据快照可能包含业务敏感信息，只存私有证据目录，不提交Git。

## 初始化契约

```sh
python scripts/capture_initialization_contract.py \
  --source-root /path/to/source/ra_triage_dashboard \
  --sqlite /private/evidence/new-fixture.sqlite \
  --output /private/evidence/sqlite-init.json
```

对旧/新源码使用不同的新文件，比较schema、初次/重复初始化和队列恢复结果。
加 `--legacy-sqlite` 可核对缺列的旧目录/账号表升级及原有行保留。
仅规范化SQLite revision触发器的墙钟`updated_at`，保留revision值；Python初始化时钟固定。
PostgreSQL初始化必须另外恢复两份副本，名称以`manual_refactor`开头，且以
`_init_old`/`_init_new`结尾，再以`--url-file`代替`--sqlite`；脚本拒绝其它库名。

## 精确版本发布

本机先推送已检查的commit，生成Git归档（含SHA的PAX头）：

```sh
git archive <full-sha> ra_triage_dashboard | gzip > /tmp/dashboard-8786.tar.gz
```

传到cloud_server后，以专用venv运行新版本中的脚本：

```sh
/volume/home/workspace/ra_triage_dashboard_venv/bin/python scripts/deploy_8786.py \
  --sha <full-sha> --expected-current <running-full-sha> \
  --archive /tmp/dashboard-8786.tar.gz \
  --evidence-dir /volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_dashboard_product_ux_20260922/<receipt-dir> \
  --baseline-url-file /private/evidence/postgres_url
```

`--check-only`只准备不可变源码、数据/API对照与完整测试。正常执行在门禁通过后切源指针，
重启固定Supervisor `ra_triage_dashboard_8786_dev`并验证SHA/health。失败恢复前指针；
并发指针变更时停止自动回滚，避免覆盖其他人的部署。配置指纹始终比对。

脚本拒绝归档SHA不符、越界路径、软硬链接、覆写已有不同源码、schema migration或依赖变化。
数据库结构/依赖变更需要单独授权工作流，不绕过此门禁。该脚本不改DB URL、服务环境或writer开关。
发布后仍须对真实页面做针对性浏览器验收，并更新CURRENT_HANDOFF；阶段4～6没有前端视觉修改。
