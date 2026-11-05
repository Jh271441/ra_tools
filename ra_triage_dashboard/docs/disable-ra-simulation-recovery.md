# 屏蔽 RA 仿真恢复规格（Manual）

## 目标与实现范围

Issue 的原屏蔽 RA 仿真任务记录可能仍在，但 bag 和 Animation 已超过产物保留期。
恢复的目标是在 Manual 的既有“屏蔽 RA 仿真”入口打开经过验收的新任务，保留原任务来源。
任务 ID 存在、Orion 显示 completed 或链接可生成，都不能单独证明产物仍可用。

当前已实现服务端只读映射和外链投影；重跑、验收和发布由受控运维流程执行。
本功能没有网页提交仿真、批量重试或自动续期接口。

- 新关联只写 Manual 自己的数据目录，不回写 Trail；不修改 GT、Review、Case 标注或模型 Run。
- 原 Trail 字段 `te_task_id_disabe_ra` 保留原值，拼写沿用既有 API 契约。
- 仿真恢复与路测 BEV/局部 BEV 采集是独立流程，不能用路测媒体替代屏蔽 RA 仿真。
- 新批次先冻结数据集、Issue 集合、选样时的 GT、原 Task/版本及配置，再通过小样本验收后批量处理。
  本轮选择“正确触发且有原任务”不代表读取入口只对某个 GT 类别有效。
- 没有原任务或原配置不完整的 Issue 单独记录；不根据邻近案例猜测配置。

## 关联读取与优先级

`GET /api/cases/{issue_id}/trail-metadata` 在既有 `external_links` 内返回关联。
沿用当前 Issue 的元数据读取、权限和延迟加载流程，不阻塞详情首屏。

| 本次读取到的状态 | 关联选择 |
|---|---|
| 本地记录通过格式校验，且元数据中的原 Task 与 `source_task_id` 相同 | 使用本地验收的新 Task 和精确版本，跳过旧 Task 版本探测 |
| Trail 元数据不可用或没有原 Task，本地记录有效 | 仍可使用本地记录 |
| 元数据中的原 Task 已变为另一个 ID | 忽略旧本地映射，使用现有 Trail 外链逻辑 |
| 本地清单缺失、损坏、超限，或记录未验收/来源不匹配 | 回退现有 Trail 外链逻辑；回退不代表旧产物已恢复 |
| 两侧均无有效任务 ID | 不构造仿真链接 |

命中本地记录时，`external_links` 提供：

| 字段 | 含义 |
|---|---|
| `disable_ra_simulation_url` | 服务端固定 Voyager 入口构造的 Ares Animation URL |
| `disable_ra_simulation_task_id` | 本次验收的新 Task ID |
| `disable_ra_simulation_task_version` | 本次验收的非负整数版本 |
| `disable_ra_simulation_source` | 固定为 `manual` |
| `disable_ra_simulation_original_task_id` | 原 Task ID，与本地 `source_task_id` 一致 |

既有 Trail 回退不补造 `source=manual`。链接必须带验收过的精确版本，不能用
`task_version=-1` 代替；Ares 的任务查询和页面结果过滤对 `-1` 的行为不同。
浏览器不提供任意目标 URL，也不根据新 Task 覆盖原 Trail 元数据。

Trail 显示元数据可来自持久快照，读取时间不等于当前源数据时间。
需要检查 Trail 是否更新原 Task 时，使用既有显式刷新流程；本地映射仍独立读取，
不固化进旧的 Trail 显示快照。快照契约见
[RA Event 与元数据缓存](ra-event-navigation-and-cache.md)。

## 持久化契约

清单位于实际运行配置的
`DASHBOARD_DATA_DIR/disable_ra_simulations/links.json`。
使用持久数据卷，不放入发布代码树或临时目录，也不假设默认数据目录就是线上目录。
代码发布、服务重启和数据恢复时应保留清单；备份时同时保留验收回执和原清单。

以下 ID 和时间仅用于说明格式，不代表真实任务已验收：

```json
{
  "schema_version": 1,
  "links": {
    "cn35667619": {
      "source_task_id": "4523469300000031",
      "task_id": "5123456700000001",
      "task_version": 0,
      "status": "completed",
      "configuration_matches_source": true,
      "output_bag_count": 1,
      "verified_at": "2026-11-01T03:00:00+08:00"
    }
  }
}
```

读取约束由 `app/simulation_links.py` 执行：

- 清单最多 1 MiB，`schema_version` 必须为整数 `1`，`links` 必须为对象。
- Issue ID 使用项目既有校验；两个 Task ID 转为字符串后必须为 12～20 位数字，发布时使用字符串。
- `task_version` 为 0～100000 的整数；布尔值不作为整数接受。
- `status=completed`、`configuration_matches_source=true`、`output_bag_count` 为正整数。
- `verified_at` 为带时区的 ISO 8601 时间。原始证据用 UTC 或明确的时区，展示时间明确为 Asia/Shanghai。

这些字段是发布流程写入的验收声明。普通 GET 只检查清单及来源一致性，
不会每次重新下载 bag、校验 Animation 或检测产物是否再次过期。

## 重跑与验收流程

1. **盘点与冻结**：分别查询原任务元数据和实际产物，记录缺失原因、原 Job/Task/版本、
   scenario、Binary、全部 task_args、runtime、资源和保留策略。
2. **小样本**：本轮先恢复 3 条，完成下方全部门禁后才处理剩余 330 条。
   后续新批次应明确自己的样本和验收回执，不把历史通过当作新批次已验收。
3. **提交重跑**：保留源 scenario、Binary、仿真业务参数及 runtime，尤其是
   `--sim_disable_loading_assist_topic`。本轮 Binary 为 `1775205`；它是本轮来源配置，
   不作为后续所有批次的硬编码值。资源或并发调整单独留账，记录调整前后值。
4. **核验产物**：任务成功后核对配置，检查当前版本的非空 bag、正文件大小、SDK 文件状态及
   可读取的格式头；检查 Animation 引用非空且无 `stage_error_animation`。
   Ares 接口读回的 Task、版本、scenario 必须一致且有输出 bag。
5. **发布与读回**：通过全部门禁才合并清单，再逐条读回 Manual API，检查新 Task、精确版本、
   `source=manual` 及原 Task 均匹配。保存发布前后清单、验收记录和 API 回执。

必须分别记录 `simulator_cache_hit=false` 的实际重算和 `true` 的平台缓存命中；
该字段缺失时记为待确认，不能默认计入实际重算。
新 Task ID 不代表实际重算；缓存命中仍须验证当前可用产物。
因果归因或同 Binary 顺序复跑使用 `prod_gen4`、`max_concurrency=1`，
需要实际重算、合理时长和推理日志才能作为归因证据。

API 读回、bag 格式头读取和 Animation 引用检查的覆盖范围分别记录，
不能据此宣称已完成全部 bag/视频解码或带登录态的页面播放验收。

## 状态、重试与幂等发布

以下是恢复台账的统计口径，不是新增的网页状态或 API 枚举：

| 阶段 | 是否计入“已恢复” |
|---|---|
| 提交已接受、任务已创建、排队或运行 | 否 |
| Orion completed，但缺少 bag/Animation、配置不符或验收未完成 | 否 |
| 验收通过但尚未发布或 Manual 读回失败 | 否；先对账已写入状态 |
| 清单已发布且 Manual API 逐条读回匹配 | 是，按冻结范围内唯一 Issue 统计 |
| 仿真失败、动画崩溃、重试耗尽或需修复源数据 | 否；保留失败和缺口 |

- 每次提交或重试前先持久化 intent，接收后保存回执。超时或结果不明时，先按工作流/
  Job/Task 只读对账，禁止盲重放提交。沿用官方克隆/重试接口，保持原配置和完整当前资源需求。
- 临时限流等可在有证据和明确预算时进行有界重试；相同断言或反复动画崩溃保留证据待修复。
  `Crashed due to memory limitation` 是动画程序对 page crash 的通用提示，
  不能仅凭它确认宿主内存不足或断言加内存即可解决。
- 发布持有同一清单的互斥锁，锁内重读、检查来源和目标冲突、合并已有记录，
  在同目录写临时文件并 fsync 后原子替换。保留旧清单和回执；不得整批覆盖其他已发布记录。
  同一 Issue/原 Task/新 Task/版本的重复发布应幂等，冲突先对账。
- 恢复监控有明确截止时间，记录进程身份和心跳；不根据旧 PID 或旧 `running` 字符串判断当前存活。
  终态未全恢复时明确保留未解决项，监控退出或到期不代表恢复完成。
- 回滚只恢复本次关联记录并保留其他新增记录；不修改远端任务历史、原 Trail 关联或人工业务数据。

## 页面与验收要求

复用 Review/问题标注已有的“屏蔽 RA 仿真”入口和共享外链组件。
新增或修改显示时沿用中英文、深浅主题、键盘及移动端约定；切换语言和 Issue 后保持正确关联，
旧 Issue 的异步结果不得覆盖新 Issue。来源以 API 审计字段核验，不将运维台账写成已上线的进度 UI。

验收至少覆盖：

- 本地有效映射、Trail 暂不可用、原 Task 已变化、空记录及各种非法/超限清单的选择行为。
- 精确 Task 版本、固定目标域名、原来源保留，以及无关 RA Event/录屏字段保持正确。
- 三条样本门禁、批量唯一 Issue 分母、重算/缓存分项、失败不计成功、清单合并与 API 读回。
- 发布/重启后读取同一持久清单；操作重试不重复提交、不丢失其他已验收关联。
- 涉及 UI 改动时覆盖 320px、390px 或 430px、1440px，以及中英文和代表性深浅主题。
  桌面浏览器视口检查与真机、登录后实际播放验收分别记录。

现有读取和路由回归入口：
[`tests/test_simulation_links.py`](../tests/test_simulation_links.py)。
发布门禁和运维验收还需各自的原生回执，单元测试不代替它们。

## 本轮恢复快照与未完成项

以下是 **2026-11-01 23:59 CST（UTC+8）** 的历史证据，后续线上现状须重新查询：

- `0821-odd2` 共 1026 条，选样时 GT 正确触发 356 条，其中有原任务的 333 条进入恢复；
  其余 23 条因缺少原任务单独排除。
- 3 条样本验收通过后处理 330 条批量；共 330/333 条已核验回填并逐条 API 读回，
  其中 321 条实际重算、9 条平台缓存命中。
- `cn35700949`（Task `4903733300000036` v1）、`cn35776589`
  （Task `4903733700000044` v1）已有新仿真 bag，但 Animation 崩溃，未发布。
- `cn35714557` 的 Task `4903733700000050` 与并发 1 的独立补跑
  `4910626300000000` 均在 18.1 秒命中同一车道序列断言，未发布。
- 本轮新输出仍沿用原 30 天保留策略。持久化关联不延长 bag/Animation 的保留期。

原始证据根：
`/volume/home/workspace/ra_triage_dashboard_deploy/recoveries/manual-disable-ra-20261101`。
`bulk-state.json`、`bulk-status.json`、`completion-check-latest.json`、
`assertion-recovery-status.json`、`publications/` 分别保留初始批量、补跑和发布证据。
发生补跑替换时，完整恢复数按同一冻结 Issue 集的实际清单及发布读回回执汇总，
不把初始失败记录改写成成功。后续进度须重新核对原生 Task、产物和 Manual 关联。

待完成：上述 3 条恢复及完整 333 条最终审计；长期产物归档/续期和可复用恢复调度尚未产品化。
若后续实现这些能力，应补充保留策略、执行预算、状态展示和相应验收。
