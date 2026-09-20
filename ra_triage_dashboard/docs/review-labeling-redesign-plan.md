# Review、标注与跨 Run 评测改造计划（续建评审稿）

- 初版：2026-09-17；本次续写：2026-09-20。
- 当前代码与线上基线：`2632977be2e679b8cd85e68774f53088e6499973`。
- 本文承接此前的 Review/标注解耦讨论，并依据已经上线的 Case 标注域重新规划后续工作。
- 范围：RA 三分类标注、模型判错复核、Review 任务分配、GT 修正候选、裁决及相关统计。已有 Routing/lane-change 意图标注不纳入本次重构。
- 后续业务确认：0522、0626、0821 的历史记录以标注为主，note 默认迁为标注依据；0206、0508 按历史批次保留/核对模型复核用途。
- 详细数据集映射、生产盘点、迁移步骤与独立 UI 设计见 [数据集迁移与独立标注页面设计](dataset-migration-and-labeling-ui-design.md)。涉及这两部分时以该补充设计为准。

## 实施状态（2026-09-20）

P1/P2 的主体能力已经提交、发布并完成生产迁移：

- 新增 frozen Workset、Label Case/revision、显式 adjudication、迁移映射、标注讨论链接、标注附件和 GT 导出批次 schema。
- 已上线模型无关的 `/case-labeling` 页面和专用 API；启动与切数据集时不请求 Runs、模型 overview 或 reviewer facets。
- writer/admin 裁决绑定当前人员 heads；任何参与来源缺交、冲突或过期都会阻止 GT 导出。
- GT 导出先固定来源 fingerprint，下载前重新检查标签与 GT；仍输出兼容的两列 XLSX，不写 Trail。
- dry-run 默认的幂等迁移工具已用于 0522、0626、0821 的生产回填与激活；三个范围均为 epoch 1、policy `case-labeling-v1`。原 annotations/comments 保留，迁移来源 Review 禁止从旧页直接删除。
- 历史 comment、回复与 comment 附件通过原记录链接复用，不重发通知；Review 截图映射为标注附件，不复制文件。

后续没有完成的部分正是当前“半成品”体验的来源：

- `/review` 仍使用 legacy mixed Review。`expected_output`、`review_status`、模型原因和缺失信息仍保存在同一 annotation 中。
- Review Gallery 的跨 Run fallback 只复用 `work_split_id=''` 的普通记录。旧 Split/任务记录即使已经表达 Issue 标签，也不会投影到另一个 Run；直接放宽 fallback 会把任务进度和模型诊断一起串到新 Run，因此不能作为最终修复。
- `/case-labeling` 已经有任务内 Label resolution 和 GT 候选，但 `/review`、Overview、原因分析及 Run Comparison 还没有消费同一份 Issue 级共享标签投影。
- GT 同步仍以 `issues.gt_label + gt_sync_labels` 保存当前 overlay，成功同步的历史版本没有形成不可变 `gt_snapshot`。
- Model Runs 仍是平铺列表和两两比较；没有 Runs 合集、合集版本、统一 Workset/标签快照或可复现评测记录。
- `issue_work_splits` 同时承担 legacy Review task、Labeling Campaign 和分配配置；缺少清晰生命周期及面向 Runs 合集的父子任务关系。

当前优先级应从“继续补 Case 标注页面”转为：先把 Issue 标签状态接回所有 Run 视图，再拆模型复核，最后补齐任务 Campaign 与 Runs 合集。

## 1. 本次要达成的结果

用户在工作台完成两类工作：

1. **标注**：根据证据判断 Case 的期望输出，记录 Issue 标签和判断依据，可以按任务做单人或多人独立标注。
2. **模型判错复核**：针对一个明确的 Run 和标签基准，分析模型输出、原因或输入哪里出了问题。

两类工作拥有独立页面和页面状态，共享 Case、媒体、任务分配、身份与历史组件，分别保存内容、计算完成度。标注页面不显示模型结果或判错复核区域。判错时发现 GT 有误，可以就地保存期望输出，进入 GT 待复核，之后通过现有导出与 Trail 更新流程处理。

本次不另建一个与 Trail 并列的“全局正式标签”。任务结果、修正候选与正式 GT 的关系固定为：

```text
人工标注/GT 修正提议 → 任务内一致结果或显式裁决 → GT 更新候选
→ 确认导出 → 外部更新 Trail → 同步核对 → 新的正式 GT 快照
```

需要简化的是用户看到的概念，而不是丢掉必要的来源信息。产品主要呈现“标注”“判错复核”“GT 待复核”；单人、多人、裁决属于生成结果的过程，在详情中可追溯。

## 2. 已核对的现状与问题

| 当前实现 | 代码落点 | 改造原因 |
|---|---|---|
| 同一个 annotation 保存期望输出、Issue Tags、是否排除、模型原因、缺失信息和截图 | `app/support/annotations.py`、`app/db_parts/review.py` | 标签判断与模型诊断混在同一版本和保存操作中 |
| `review_status` 由期望输出与 GT 比较产生 | `app/review_workflow.py::derive_review_status` | `reviewed` 实际表示与 GT 一致，不能代表模型归因完成 |
| 任务中已有 Run、筛选快照、成员和人员分配信息 | `issue_work_splits`、`review_work_assignments` | 可以复用任务基础设施，但需区分 Run 是选样来源还是被复核对象 |
| Gallery 默认按任务成员、当前用户或 base/cross 规则选记录 | `app/db_parts/cases.py::_gallery_annotation_join` | “给我编辑的版本”与“团队统计采用的结果”没有统一分工 |
| 原因分析以最近追加的成员 head 作为代表行，存在任务结果时压过普通记录 | `app/support/review_payloads.py` | 代表行可以用于历史展示，不能直接作为已经解决的标签结果 |
| GT 更新导出检查标签有效、不同于 GT、Issue 去重 | `app/routers/analysis.py::_trail_expected_output_rows` | 未把冲突、未完成、裁决过期等作为导出限制 |
| GT 同步保存当前 overlay，内容变化时替换 `gt_sync_labels` 并更新当前 Issue GT | `app/db_parts/gt_sync.py` | 当前最新 GT 可查询，但不能只依靠这张表还原任意历史评测基准 |
| 非任务成员可以提交普通 Review，不绑定该盲标 Split | `static/js/review-draft.js::reviewWorkSplitBinding` | 保留已发布修复；任务内提交与任务外补充仍需要明确归属 |

这些是本地代码事实。补充设计已记录生产只读汇总，未逐条审阅历史正文；正式迁移仍须生成逐记录映射清单和一致性快照。

## 3. 收敛后的领域模型

### 3.1 两种任务目的，其余信息分别归属

| 概念 | 回答的问题 | 约束 |
|---|---|---|
| 数据集版本 | Case 来自哪个数据集？ | 保留现有 baseline membership，标签更新不改变成员集合 |
| 工作集 Workset | 本次选中了哪些 Case，为什么选它们？ | 冻结成员、顺序、筛选条件和来源；可以是整个数据集，也可以是子集 |
| 任务 Task | 谁来完成什么工作？ | 新任务仅有 `labeling`、`model_review` 两种目的；复用现有分配/转派能力 |
| 标注版本 | 某个人对这个 Case 的判断是什么？ | 作者独立追加版本，不以另一作者的新版本覆盖自己的判断 |
| 标注结果 Resolution | 在该标注范围中采用什么结论？ | 来自单人提交、多人一致或显式裁决；保留来源版本 |
| 判错版本 | 对某个 Run 的具体诊断是什么？ | 绑定 Run、Case、GT/标签基准和可选任务；单独记录完成情况 |
| GT 快照 | 正式评测采用哪版 Trail 标签？ | 可复现、带覆盖与内容 hash；已保存快照不被后续同步改写 |

不增加 `ordinary_review / blind_review / adjudication_review` 这一套顶层类型。裁决是一种明确的结果选择操作，独立标注是任务的执行方式。

第一版不增加 `isolated/candidate/authoritative` 等多套任务发布策略。任务产出统一作为本地结果；进入正式 GT 继续使用同一条 Trail 工作流。

### 3.2 Run 的两个角色必须分开

- `selection_source_run_id`：用于选样。例如“模型 A 在 0821 上低置信度的 150 个 Case”。保存它是为了说明这个子集的业务含义，不限制这些标注只能供模型 A 使用。
- `evaluation_run_id`：判错复核的对象。模型原因、缺失输入和诊断截图属于这一 Run。

标注任务可带第一个字段，不要求第二个字段。模型复核任务必须指定第二个字段。每个任务第一版只复核一个 Run；跨 Run 比较通过复用同一个 Workset 和同一标签快照完成。

工作集创建保存 dataset scope、去重后的 Issue IDs、筛选条件、来源 Run/预测 hash、筛选时的 GT 版本和创建人。提交创建时在服务端重新解析并冻结所选集合；成员数变化需展示实际创建结果。后续浏览时不重新执行筛选条件改变成员。

### 3.3 “结果作用域”不等于“页面筛选条件”

三个主要结果键为：

```text
任务标注结果：  (label_task_id, baseline_scope, issue_id)
独立 GT 修正：  (correction_case_id) → dataset/Issue/所见 GT 与证据版本
模型判错记录：  (review_task_id 或自由复核范围, run_id, issue_id, author)
```

同一个 Issue 可以属于多个任务。每个任务先计算自己的结果。跨任务展示可并排、汇总和对照，但没有默认“最新任务覆盖所有旧任务”的规则。

从模型复核提出的独立 GT 修正，保存来源 Run/Review 作为追溯字段。相同 Issue、相同所见 GT 和相同标签/证据定义下的修正可以归入同一个修正事项；任务内标注仍留在原任务。跨事项冲突由 GT 更新候选汇总时提示，使用显式选择或裁决解决。

### 3.4 Runs 合集是评测容器，不是标签作用域

Runs 合集用于把同一数据集上的若干不可变 Model Run 组织起来，例如“ckpt330 全量、confidence batch3、rand10”。合集本身不拥有 GT、人工标注或模型原因；它保存成员关系与默认评测上下文。

```text
Run Collection revision
  + Frozen Workset
  + GT snapshot 或 Label snapshot
  + Scoring policy
  = Evaluation context
```

合集成员每次变更生成新 revision。已有评测继续引用旧 revision，不能因为后来加入一个 Run 而改变历史分母或比较结果。合集中的每个 Run 共享同一份 Issue 标签参考，但模型输出、判错原因和复核完成度继续按 Run 隔离。

合集第一版提供：

- 保存/命名一组 Runs，并固定成员顺序和基准 Run。
- 选择一个 Workset 与一个标签参考版本，对全部成员计算覆盖、Match/Mismatch/No GT/NONE 和成对变化。
- 查看某个 Issue 在全部成员中的预测横向表，以及一份共享标签状态。
- 从合集创建任务组：Labeling 只创建一个共享任务；Model Review 为每个目标 Run 创建独立子任务，并共用 Workset 与标签快照。

合集不自动合并不同 Run 的模型原因，也不把“其他 Run 已复核”算作当前 Run 完成。需要复用原因时，用户显式“引用为起点”，新记录保存来源 revision ID。

## 4. 用户操作流程

### 4.1 从 Run 筛选子集，先打标

1. 在 Runs/Gallery 中筛选，例如某个 Run 的全部有输出 Case、低置信度 Case、缺 GT Case。
2. 选择“创建标注任务”，预览实际数量、来源 Run、筛选条件和数据集。
3. 分配人员，设置每 Case 的标注人数与交叉比例；工作集固定下来。
4. 进入标注模式，只要求标签判断所需字段；来源 Run 在任务说明中保留。
5. 单人 Case 得到单人结果；多人 Case 按实际应交人数统计，冲突进入裁决。
6. 选取已解决的 Case 生成版本化标签结果快照，提交 GT 更新候选；可以分批处理，无需等整个任务关闭。
7. Trail 更新和同步完成后，用正式 GT 快照评测来源 Run 或其他 Run，再创建判错复核任务。

标注页面不提供模型预测、confidence、model reason、模型对照或判错复核控件，使用不含模型结果的专用 payload。初标时 GT 对照不主动展示，GT 核对/裁决流程按需提供参考。现有“盲标”允许查看历史，因此第一版准确称为“独立标注/交叉复核”，保留既有历史行为。严格限制同事历史答案属于进一步的可见性设计，不以简单隐藏控件冒充严格双盲。

### 4.2 针对模型判错做 Review

1. 进入指定 Run、工作集和标签基准的复核队列。
2. 页面显示模型输出/Reason、采用的 GT 与版本、Case 媒体。
3. 填写模型诊断、缺失信息及可选截图，保存“模型复核”。
4. 完成度由模型复核自身的提交/完成动作决定；仅填写期望输出不再被计入完成归因。

多人对模型的自由文本原因不同，不自动变成“标签冲突”，也不比较文本是否一致。每人意见可以并列展示。Issue 级模型诊断统计按 Case 去重，人员工作量按人员提交统计。

### 4.3 Review 时发现 GT 错误

1. 就地点击“GT 待复核”，填写期望输出；保留标注依据/截图入口。
2. 保存一个标签修正提议，同时关联当前 Run、Review 和所见 GT 版本。
3. 页面立即显示“GT 待复核”，不强迫填写模型判错原因；也不必手工再建一个分配任务。
4. 在 GT 待复核队列中对照证据、处理相互矛盾的提议，确认本次拟导出的标签。
5. 按现有格式导出到 Trail，外部更新后同步核对。
6. 新 GT 与预测一致时，该 Case 当前无需继续作为模型 label 错误归因；若仍不一致，可继续原 Run 的诊断。

GT 可疑与模型诊断可以同时存在。即使 GT 有误，模型也可能存在独立问题；原始 note 和证据继续保留。标签修正不代表自动否定所有模型诊断，GT 更新后不自动把旧文本改写成新结论。

### 4.4 非任务成员参与

- writer/admin 可以提交任务外补充或独立 GT 修正。
- 只有被分配的人员提交到该任务的人员槽位，任务进度才增加。
- writer/admin 无论是否在任务内，都可以对已展示的冲突执行显式裁决，包括原冲突参与者。
- 裁决不算“又完成了一个分配槽位”，普通补充也不直接变成裁决。
- 任务创建、转派和人员管理沿用现有管理员权限；开放 writer 裁决不隐含开放其他管理能力。

## 5. 页面与字段拆分

新增独立 `/case-labeling` 标注页面，保留 `/review` 模型复核页面。两个页面使用同一套媒体、Case 导航、标签、附件、历史与讨论组件，各自拥有控制器、查询状态和保存动作。任务入口自动带入目标工作区、Task 和工作集；标注页不会继承自由模型复核入口的 Run 选择。现有 `/intent-labeling` 属于其他标注业务，保持独立。

| 现有字段 | 新归属 | 处理方式 |
|---|---|---|
| `expected_output / label` | 标注或 GT 修正提议 | 保留三分类及现有 Tags 推导规则 |
| `tags` | Case 标注证据 | 保留原始作者/任务版本，不能自动将不同人的全部 Tags 合并成一份最终结论 |
| `note` | 分成 `label_rationale` 与 `model_reason` | 0522/0626/0821 默认原样迁为标注依据；0206/0508 按批次处理，真正混合的正文保留历史说明 |
| `missing_evidence` | 按记录用途归属 | 三个标注集的历史值保留为标注证据缺口，模型复核的值归入模型诊断；不靠有无该字段猜测历史用途 |
| `is_excluded` | 排除提议/判断 | 保留现有问题排除工作流与写入边界，不等同于一个三分类标签或 GT 更新 |
| screenshots | 对应记录的证据 | 标注和模型诊断分别归属，可明确引用既有附件，保留来源 |
| `review_status` | 兼容展示字段 | 新逻辑拆成标签与 GT 的关系、模型复核进度，不再作为万能状态 |

主要交互：

- 标注页主按钮“保存标注”；模型复核页主按钮“保存模型复核”；分别拥有页面状态和数据接口。
- 模型模式内的小面板“GT 待复核”有独立保存动作，保存后留在当前 Case。
- 冲突面板列出人员结果及证据，点击“裁决”明确提交最终标签和依据。
- Enter 跟随当前活动表单；裁决通过明确确认按钮提交，避免普通 Review 快捷键误裁决。
- 切换 Run/任务时，草稿、上传队列和异步回填按各自范围隔离。失败附件上传在原范围恢复，不污染另一个任务或 Run。
- 列表默认只呈现当前动作相关状态；单人/多人/裁决方法、原始冲突等放详情，不为每个内部字段增加 badge。
- 任务分配页选择“标注任务 / 模型复核任务”。第一版不做独立的 Workset 管理中心；工作集在创建与复用任务时生成。

## 6. 状态、裁决与导出规则

### 6.1 分开计算状态

| 状态对象 | 最小状态/信息 | 不代表什么 |
|---|---|---|
| 标签结果 | 未解决、已解决、冲突、需重新确认；另带 `single/consensus/adjudication` 方法 | 不是模型原因的完成度 |
| 任务完成度 | 已交人数 / 应交人数；已提交 Case / 任务 Case | 裁决不是额外标注人，其他任务的提交不计入 |
| GT 关系 | 一致、缺 GT、GT 待复核 | 差异本身不能证明正式 GT 已错 |
| 模型复核 | 待复核、已保存草稿/进行中、已完成；可带依赖变更提示 | 模型匹配 GT 不表示人已完成复核 |
| 导出/同步记录 | 已导出、待核对、Trail 当前值已核对 | 已导出不表示已写入 Trail |

多人任务的 `1/2` 提交可以显示、筛选和导出到原始明细，但不能默认为已经达成一致。交叉比例小于 100% 时，按每个 Case 的实际应交人数计算，不按整个任务统一人数套用。

一致性第一版关注期望输出；Tags、notes 保留每人的证据。排除判断若不一致，应单独呈现争议，不能因为标签一致就自动生成问题排除写入候选。

### 6.2 显式裁决

裁决记录关联精确的标注范围、Case、参与判断的版本集合、所见 GT、前一裁决版本、裁决人和理由。结果允许采用某人的标签，也允许基于证据提出第三个合法标签。

授权条件固定为服务端验证身份且角色为 writer/admin。新裁决接口在任何部署模式下都独立执行该校验；不能直接复用 development 模式可能为 true 的 `session.can_write` 来推断可裁决。

保存时在一个数据库事务内锁定结果对象，核对人员分配版本、源提交 heads 和前一结果版本，再追加裁决和更新结果指针。PostgreSQL 使用数据库锁/条件更新，不能仅依赖进程内 `_write_lock`。不匹配返回 409，保留用户草稿。

单个作者的后续版本按该作者版本链取当前 head。跨作者、跨任务的有效结果通过结果规则或显式选择产生；不按时间戳或最大 annotation ID 仲裁。

裁决后的变更处理：

- 被裁决的标注 head、相关成员分配或实际标签证据发生变化：保留旧裁决，当前结果提示需重新确认。
- 无关任务提交、讨论评论、模型原因更新：不影响这项标签裁决。
- GT 同步仅改变该 Case 的 GT 关系和修正提议适用性；不因为整个数据集 hash 改变，就让全部任务的人工判断失效。
- 撤回裁决或修正引用源使用有审计记录的操作；被快照/裁决引用的源不能经旧删除接口直接物理删除。撤回不自动复活更早裁决为有效结果，需要明确恢复。

### 6.3 GT 更新候选与导出

保留“期望输出 → GT 待复核 → 导出 → 外部 Trail 更新”的用户流程。增加一页/一层导出预览，明确本次采用哪些标签来源。

单人修正无需每个 Case 多点一次审批；writer 可以在导出预览中批量确认。多人冲突须先裁决，未完成和过期结果留在待处理队列。裁决过的结果不再增加第二个管理员审批要求。

允许进入正式 GT 更新表的记录必须满足：

1. 期望输出是有效三分类值，与最新已核验 GT 不同，或用于补齐缺 GT。
2. 来源已经形成可用结果；当前无未解决冲突、必要缺交或过期依赖。
3. 本次导出已显式采用这一来源版本。
4. 多任务/多 Run 产生的修正候选若指向同一 Issue 且值不同，先展示冲突，不能按遍历顺序去重。
5. 导出预览后源记录或该 Case 的 GT 变化时重新核验。GT 已等于期望值则提示无需更新；变成其他值则回到复核。

Trail 文件仍保留精确的两列 `issue_id`、`期望输出`，确保现有导入工具兼容。来源 Task/Run、GT 旧值、snapshot hash、结果版本、确认人、export ID 等留在服务端导出清单和可另行下载的审计明细中。

导出本身不写 Trail。外部更新后，既有 GT 同步读取 Trail，再逐项对照本次导出值。仅观察到值一致时可以标记“Trail 值已核对”；没有外部执行回执时，不声称是本次文件造成了更新。局部更新、后续再次变化都逐 Case 呈现。

## 7. 共享、隔离和统计口径

### 7.1 跨 Run 与跨任务

- 正式 GT 在同一数据集版本与同一 GT 快照下共享，所有对比 Run 使用同一套参考标签。
- 本地任务标签可通过明确选择同一个标签快照供多个 Run 做诊断对照；页面必须标注“本地标注基准”，不能称为正式 Trail GT 指标。
- 模型原因、缺失信息和复核完成度按 Run、任务、作者隔离。其他 Run 历史可以展示为参考，但不能用来填充当前 Run 的完成度。
- 从已有内容复用到新 Run 时，用户显式引用来源并确认，保存新 Run 的记录及来源 ID。
- 新任务默认独立，旧任务结果只作参考；若希望以已有结果为起点，创建时显式选择快照并记录来源。沿用条目不计为本任务“新提交”。
- 没选择任务时，展示自由复核或有明确来源的汇总；不自动把用户放入最新 Split。任务成员进入任务页时总是有明确 task ID。

### 7.2 不强行用一个 effective_review 回答所有问题

统一基础查询与来源规则，但保留三个明确的读取出口：

```text
resolve_label_result(label_scope, issue_id)
project_model_reviews(run_id, review_scope, issue_id, author_filter)
build_gt_update_candidates(selected_label_results, current_gt)
```

Gallery、分析、导出、Overview 使用对应出口及统一过滤器，避免各写一套优先级 SQL。个人编辑返回自己的 head，团队统计返回团队结果；差异有明确用途，而不是依赖访问者身份改变团队口径。

读取时批量解析当前页/过滤集合，派生筛选在计数与分页之前执行。不能逐个 Case 发数据库查询，再在分页之后过滤。

| 统计 | 一条记录/分母的单位 | 去重和说明 |
|---|---|---|
| 标注人员进度 | 任务内有效人员槽位 | 同一人同 Case 多次修改仍算一个已交槽位 |
| 标注结果覆盖 | 任务内 Issue | 同一 Case 双人标注加一次裁决，结果仍为一条 |
| 冲突与裁决 | 任务内 Issue | 原始冲突率与当前未解决冲突数分别统计，裁决不抹去原始分歧 |
| 模型原因覆盖 | Run × 复核范围 × Issue | 标签提议不算模型原因完成，人员明细独立提供 |
| 跨任务总览 | 数据集/Run 下的唯一 Issue，或明确的任务明细 | 不直接相加多个重叠任务的 Case 数；多来源分歧可见 |
| 正式模型指标 | 固定 Workset × Run predictions × 正式 GT 快照 | 缺预测、缺标签、排除策略、支持的标签语义明确记录 |
| 本地修正对照 | 同样的预测及明确选定的本地标签快照 | 单独标为诊断，不替代正式评测 |

修正此前讨论中的一个建议：GT 待复核 Case 不自动从已有正式准确率分母中消失。正式指标仍按绑定快照和既有评分规则计算，同时列出有争议数量；可另提供显式过滤的诊断视图，展示过滤后分母。GT 更新后创建新评测版本，并可对照旧结果。

按某模型预测筛出的工作集，其指标只代表该子集。即使多个 Run 在这份固定子集上可直接对照，也要保留选样来源，不宣称覆盖整个数据集。

### 7.3 Review 页面采用组合投影

每个 Review Case 的读模型固定为：

```text
当前 Case
= 当前 GT snapshot 中的正式 GT
+ Issue 级共享标签状态
+ 当前 Run 的 prediction/comparison
+ 当前 Run 的模型复核状态与原因
+ 可选的当前任务分配上下文
```

Issue 级共享标签状态由 `baseline_scope + issue_id` 解析，不读取“当前 Run 最新 annotation”来决定。它至少返回：

```text
state: none | pending | resolved | conflict | stale
expected_output
gt_relation: matches_gt | differs_from_gt | fills_missing_gt | unknown
method: single | consensus | adjudication
source_task_ids[]
source_revision_ids[]
```

UI 将其映射为独立状态：

- `resolved + matches_gt`：显示“与 GT 一致”。
- `resolved + differs_from_gt/fills_missing_gt`：显示“GT 待复核”。
- `conflict/stale`：显示“标签冲突/需重新确认”。
- `none/pending`：不制造一个已完成标签结论。

这些状态在两个重叠 Run 中保持一致。当前 Run 是否完成判错复核，仍只看该 Run 的 model-review 记录。任务外查看可以读取共享标签及来源，但不会增加任务提交数、人员工作量或当前 Run 的复核完成度。

因此，当前 `_gallery_annotation_join` 的 ordinary fallback 只保留为 legacy 模型复核兼容层。Split 记录不通过扩大 fallback 来跨 Run 共享；迁移后的 Label resolution 通过共享标签投影进入页面。这样可直接覆盖 `d4b...` 与 `95dc...` 中重叠 Issue 的需求，同时不把旧 Run 的判错原因错误地算给 rand10。

### 7.4 讨论使用显式频道，不按页面偶然合并

当前 `D` 快捷键共用同一个讨论弹窗，但数据作用域不同：

```text
判错复核讨论： (issue_id, model_run_id)
Case 标注讨论： (baseline_scope, issue_id, optional label_task_id)
```

- `/review` 的讨论严格绑定当前 Run；`run=''` 是单独的未绑定频道。回复也必须留在同一 Issue/Run。另一个 Run 当前不会读取或命中该线程。
- `/case-labeling` 通过 `label_comment_links` 使用 Issue/Task 频道。指定 Task 时读取该 Task 与 Case 级公共讨论；未指定 Task 时可以汇总该 Issue 的标注讨论。`source_run_id` 只是迁移/选样来源，不限制读取。
- 评论仍与 Review/Label revision 分离，不改变 GT、标签结果、模型复核状态或任务进度。

目标 UI 在 `D` 弹窗中明确显示频道：

1. “Issue / 标注讨论”：跨 Runs 共享，可选当前 Labeling Campaign；用于证据、标签判断和 GT 复核。
2. “当前 Run 讨论”：只属于当前模型 Run；用于模型输出、Prompt、输入和判错原因。
3. “其他 Runs 讨论”：只读参考入口，按 Run 分组展示；不会计入当前 Run 的评论筛选、通知或复核完成度。用户若要回复，先明确切换到目标 Run 频道。

Runs 合集页面可以汇总各频道的未读/评论数，但不把不同 Run 的回复树合并成一个线程。分享链接继续固定频道与 comment ID，刷新后必须打开同一个上下文。

## 8. 数据与 API 方案

### 8.1 推荐的持久化边界

保留 `annotations` 及原有 API 作为历史兼容层。新标注和模型诊断使用独立的结构化版本记录，共享身份、附件存储、通知与乐观锁基础组件。

| 逻辑实体/建议表 | 关键内容 | 第一版策略 |
|---|---|---|
| `review_worksets`、`review_workset_items` | 数据集、冻结成员、来源 Run/GT、筛选快照、hash | 任务创建时生成，可复用；不增加独立管理界面 |
| 扩展 `issue_work_splits` | task kind、workset 引用、被复核 Run、标签基准、状态、配置版本、可选 task group | 物理表先不改名，代码/API 统一称 Campaign；旧记录保留 `legacy` 语义 |
| 复用 `review_work_assignments` 与转派历史 | task/Issue/assignee 及角色、分配版本 | 人员变更不改变 Workset 的成员集合 |
| `label_cases`、`label_revisions` | task 或修正事项、Issue、作者链、期望输出、Tags、依据、证据/所见 GT | task 为空表示自由修正；Case 的 current-result 指针为并发锁定对象 |
| `label_resolutions` | 单人/一致/裁决的结果与精确输入版本、显式替代关系 | append-only；派生 current 状态可以重建 |
| `model_review_revisions` | Run、可选 Task、GT/标签参考、作者、模型原因、缺失信息、完成状态 | 只保存模型诊断，不写 GT |
| `label_result_snapshots` 及成员清单 | 本地任务结果的不可变集合、覆盖、源 resolution IDs | 支持任务输出/跨 Run 诊断引用，标明非正式 GT |
| `gt_snapshots` 及成员清单 | 完整成功 Trail 读取的标签版本、覆盖/hash | 保留既有当前 overlay 作为读取加速；历史版本另外保留 |
| `gt_export_batches` 及条目 | 导出时的候选、确认、GT 旧值、目标值、文件 hash、核对状态 | 导出/核对可追溯，不实现 GT 写入 API |
| `run_collections`、`run_collection_revisions`、`run_collection_members` | 合集身份、不可变成员版本、顺序及基准 Run | 编辑合集产生新 revision；不复制或修改 Model Run |
| `evaluation_contexts` | Collection revision、Workset、参考快照、评分契约/排除集合版本、结果 hash | 复用已有模型预测；生成新指标不要求重新推理 |
| `review_task_groups` | 从 Runs 合集批量创建的任务组及子 Campaign | Labeling 组只有一个共享任务；Model Review 组按 Run 建子任务 |

这是最终职责划分，不要求一个 migration 同时创建所有表。当前已存在 `review_worksets`、Label tables 和 Label GT export tables；GT snapshots、model-review、Runs 合集与 evaluation contexts 属于后续 migration。源版本关联和 snapshot items 使用明确的关联表或受约束的成员清单，避免把需要查验的版本关系放进不可核对的自由 JSON。

标注和模型诊断的附件不再只能绑定旧 annotation ID。抽取可复用的附件 blob/存储操作，新建明确的 owner 关联，保留原 URL 与原附件所有权；历史引用源存在时，不删除其文件。截图、版本记录、关联与通知入队仍保持事务一致性。

每条新版本保留作者、服务端身份来源、创建时间、supersedes ID、来源记录 ID。已有字段值如 note 的具体语义无法确定时保存为 legacy，不伪造标注依据或裁决。

按用户已确认的业务用途，0522/0626/0821 的 note 默认语义已明确，原样保存为标注依据。只有明确例外或 0206/0508 中未能归类的混合记录保留 legacy；不把三个标注集整体降级为待归类历史。

### 8.2 建议接口

路径名称可在实施时贴合现有路由；操作边界应固定。

| 操作 | 建议接口 | 服务端责任 |
|---|---|---|
| 冻结选样 | `POST /api/review-worksets` | 校验数据集/Run/筛选，固定成员与来源 |
| 创建两类任务 | 现有 work-split 创建接口扩展 task kind | 校验任务目的、必需引用和配置快照 |
| 读取 Issue 共享标签 | `GET /api/issue-label-states`，并批量嵌入 Case 列表/详情 | 在分页与计数前统一解析 Label resolution、跨任务冲突和 GT 关系 |
| 标注详情/列表 | 独立 labeling detail/summary 接口 | 只返回标注需要的事实、媒体、历史和任务，不加载 predictions 或推理 jobs |
| 就地提出 GT 修正 | `POST /api/cases/{issue_id}/gt-corrections` | 原子查找/创建兼容的修正事项并保存首个版本，记录来源 Review |
| 保存标注/自由修正 | `POST /api/label-cases/{id}/revisions` | 范围、身份、作者版本与标签契约；支持附件 |
| 查看结果/源版本 | `GET /api/label-cases/{id}` | 返回 task result、GT 关系、当前 heads 与裁决来源 |
| 显式裁决 | `POST /api/label-cases/{id}/adjudications` | writer/admin、源指纹、前一结果版本、事务锁 |
| 保存模型诊断 | `POST /api/model-review-cases/{id}/revisions` | 校验 Run、Task、参考快照与作者版本 |
| 管理 Runs 合集 | `POST/GET/PATCH /api/run-collections` | 创建合集；成员变化生成不可变 revision，校验同一数据集覆盖 |
| 创建评测上下文 | `POST /api/evaluation-contexts` | 固定 collection revision、Workset、标签参考与评分策略 |
| 从合集创建任务组 | `POST /api/review-task-groups` | Labeling 创建一个共享 Campaign；Model Review 按 Run 创建子 Campaign |
| GT 更新预览 | `POST /api/gt-update-previews` | 固定候选来源、检测冲突/过期/重复 Issue |
| 确认导出 | `POST /api/gt-update-exports` | 再核验、生成导出批次与现有两列文件 |
| 同步核对 | 复用 GT 同步流程及批次状态读取 | 完整读取后更新当前 GT、追加快照、核对批次 |

写请求包含 `request_id` 和 `expected_previous_revision_id`；裁决/导出另外包含 `expected_result_revision_id`、源 fingerprint。重复请求返回同一已提交结果，超时重试不追加两次。JSON 与附件接口遵循相同规则。

GT 修正与模型原因都可以在同一页面操作，但使用各自保存事务和成功提示；不能出现一处保存失败却让另一处误报“整体已保存”。

### 8.3 代码落点

| 区域 | 现有主要文件 | 计划 |
|---|---|---|
| 标签契约 | `app/review_workflow.py` | 保留三分类/Tags 推导，抽离标签结果与 GT 关系的派生逻辑 |
| 保存 | `app/support/annotations.py`、`app/routers/case_annotations.py` | 兼容旧接口，新写入进入明确的 labeling/model-review 服务 |
| 持久化 | `app/db_parts/core.py`、`review.py`、`cases.py` | 新增域模块、schema 与批量查询，减少继续向超大 cases.py 堆积 |
| 结果/分析 | `app/support/review_payloads.py`、`app/review_analysis.py` | 拆分标签结果、模型原因统计与 legacy projection |
| 导出 | `app/routers/analysis.py` | 普通明细导出与 GT 更新导出分别调用各自领域服务 |
| GT 版本 | `app/db_parts/gt_sync.py` 与现有同步入口 | 保留当前 overlay，增加不可变版本及批次核对 |
| 表单与草稿 | `static/js/review-form.js`、`review-draft.js`、`review-attachments.js` | 提取共享组件，两页独立控制器与上下文，隔离草稿/上传回填 |
| 任务与分析 UI | `review-assignments.js`、`work-split.js`、`analysis.js`、`routing.js` | 明确任务目的/结果范围、URL 恢复、精简状态显示 |
| 排除工作流 | `app/routers/trail_update/` | 先保持现有独立协议；后续适配明确的排除提议，不从新模型原因记录推断写入 |
| 文档与测试 | README、域契约、tests | 写清统计分母、历史兼容和 GT 权威边界 |

## 9. 历史数据兼容与迁移

采用“只读盘点 → 兼容映射 → 影子对照 → 分范围切写 → 保留历史”的路径。

1. 盘点 annotations 中普通/任务记录数、Run/Task 引用、supersedes 链、附件/评论关联、未验证作者、跨 Task 的同 Case 冲突及当前导出规模。
2. 旧 annotation ID、作者、原始 note、时间和来源不可改写。建立映射记录，重复执行以源 ID 和映射版本去重，不产生重复提交。
3. 旧非空 label/可推导 Tags 可作为“历史标签提议”；没有确认依据时不升级为显式裁决或正式 GT。
4. 0522/0626/0821 的旧 note 默认迁为标注依据；讨论 comments 保留消息/回复语义并迁为标注讨论。0206/0508 按批次核对，未确定的混合 note 保留“历史 Review 说明”，不自动复制成两个独立已完成任务。
5. 0821 三个旧 Split 明确迁为标注任务，其余按用途清单处理；利用冻结的 assignees/filter snapshot 和转派历史恢复工作集。若原成员记录不完整，标记覆盖未知，不能重跑当前筛选伪装成历史子集。
6. 旧单人任务曾借用普通 Review 流，不能因为作者和 Issue 相同就把旧 Review 算成本任务新交付；保留旧口径或显式映射，无法确认的标记为历史引用。
7. 旧 `run=none` 和 `work_split` 链接先映射到明确的历史视图；新任务使用 task/workset/reference 参数。既有深链接、分页和筛选可继续打开。
8. 对同一上下文始终只有一个写入路径。新旧数据可以组合读取，但不采用两个接口双写再最终一致的方案。
9. 数据库已有当前 GT 从迁移时起保存为带来源的初始快照。此前已经丢失的历史 GT 不从最新 GT 猜回去，标记历史参考不可重建。
10. 浏览器旧草稿保留原 key。新草稿 key 包含域、Task/修正事项、Run、Issue 和当前作者；第一次命中旧草稿可提示恢复为当前模式，不自动删除或跨域提交。

## 10. 分阶段交付

### 已完成基线：原 P0/P1/P2 主体

- 领域规则、迁移清单、Workset、Label Case/revision/resolution、writer 裁决、GT 候选/导出批次和独立 Case 标注页已经落地。
- 0522、0626、0821 已迁移并激活；0821 原任务/来源关系已经保留。
- 仍未完成的原 P1 项是不可变 GT snapshot 和 Review 页内独立 GT 修正入口；原 P3/P4 基本尚未开始。

### S1：跨 Run 共享 Issue 标签投影（建议下一轮先做）

目标是立即解决“两个 Run 的重叠 Issue 看不到同一份 GT 待复核/与 GT 一致状态”，且不污染 Run 级判错进度。

后端：

1. 在 Labeling domain 新增批量 `project_issue_label_states(baseline_scope, issue_ids)`。
2. 一次查询当前页/筛选全集涉及的 Label Cases、人员 heads、resolution 与当前 GT；在分页和计数前完成状态解析。
3. 同一 Issue 若所有可用结果得到唯一标签，返回 `resolved`；不同任务给出不同标签返回 `conflict`；依赖变化返回 `stale`；缺交保留 `pending`。
4. 单独派生 `gt_relation`，不再复用 annotation 的 `review_status`。
5. `/api/cases`、Issue detail、Overview 和筛选 API 返回相同 `label_state`，来源包含 Task/revision/method，但默认列表不展开全部历史。

前端：

1. Review 卡片拆成“共享标签状态”和“当前 Run 判错复核”两行。
2. `GT 待复核 / 与 GT 一致 / 标签冲突`来自 `label_state`；模型原因、reviewer、完成状态来自当前 Run。
3. 点击共享状态打开来源任务/裁决的只读历史；需要修改时跳到 `/case-labeling` 的准确 Task/Issue。
4. 保持 Run 编辑表单只编辑当前 Run 的模型复核，不把共享标签复制成一个新 annotation。

兼容策略：

- 不扩大 `_gallery_annotation_join` 对 Split annotation 的 fallback。
- 已迁移范围读取 Label resolution；未迁移的 0206/0508 暂时继续显示 legacy 状态并明确标为“历史 Review”。
- S1 可以不增加数据库表，适合作为首个小版本上线，并先在当前两个 Run 的重叠 Issue 上验收。

验收：

- `d4b519b7…` 与 `95dc9002…` 的同一 0821 Issue 显示相同共享标签状态及来源。
- rand10 不增加模型复核完成数，也不继承旧 Run 的 note、missing evidence 或 reviewer。
- 源任务出现新冲突时，两个 Run 同时显示“标签冲突”；旧的正式指标仍绑定原 GT 口径。

### S2：不可变 GT/Label 快照与可复现参考

1. 新增 content-addressed `gt_snapshots`/items；每次完整 Trail 同步创建或复用一个快照，再更新 active pointer。现有 overlay 继续作为当前读取缓存。
2. 用切换时的当前 overlay 生成第一份可确认快照；更早历史无法重建时明确标记，不从当前值倒推。
3. 新增 `label_result_snapshots`/items，从已解决 Label resolution 固定一个 Workset 的本地标签参考。
4. GT 导出批次绑定 source GT snapshot、目标 revisions 和目标值；后续同步在新 snapshot 上逐项核对 `matched / not_applied / changed_again`。
5. 正式评测必须引用 GT snapshot；使用 Label snapshot 的结果标为“本地标注对照”。普通 Review 页面可以提供“当前”视图，但展示 active snapshot ID/时间。

验收：GT 更新不会改写旧评测；同一 Run 对旧/新 GT snapshot 可复算并说明差异；导出完成不再等同于 Trail 已更新。

### S3：模型判错复核独立存储与状态

1. 增加 `model_review_cases/revisions/attachments`，键为 Run、Issue、可选 Campaign、标签参考、作者；note 与 missing evidence 只表示模型诊断。
2. 明确状态 `pending / in_progress / completed / blocked_by_label`。状态由模型复核操作产生，不再由 expected output 与 GT 比较推导。
3. `/review` 的主保存动作写 model-review；“GT 有误”小面板写 Label domain，并保留当前 Run/revision 作为来源。
4. Gallery、Overview、Reason Analysis、reviewer facet、CSV/XLSX 先做新旧影子对照，再按数据集/任务切换到 model-review 投影。现有 `/review-analysis` 和侧栏“原因聚类”继续专门回答“模型为什么判错”，不混入 Case 标注依据。
5. 0206/0508 按已确认批次迁移；混合 note 原文保留为 legacy evidence，不自动拆成两个已完成记录。0522/0626/0821 的已迁移标签继续只在 Label domain 生效。
6. 判错复核讨论继续以 `Issue + evaluation Run` 为频道；D 弹窗增加“Issue / 标注讨论”和“其他 Runs 讨论”只读入口，但当前 Run 的评论筛选、通知和完成度只读取本频道。

验收：Run A 和 Run B 的诊断、完成度、评论及附件互不填充；共享标签变化只更新 `blocked_by_label`/参考提示，不改写历史原因；填写标签不会算作模型归因完成。

### S4：任务分配收敛为 Campaign

1. 代码、API 和 UI 统一使用 Campaign 术语，物理上先扩展 `issue_work_splits`，避免重写已迁移 ID 和深链接。
2. Campaign 固定 `purpose = labeling | model_review`、Workset、可选 `evaluation_run_id`、reference snapshot、`draft/active/closed/cancelled/superseded` 生命周期及配置 revision。
3. Labeling Campaign 不绑定 evaluation Run；`selection_source_run_id` 只保留在 Workset 作为选样来源。Model Review Campaign 必须绑定一个 evaluation Run。
4. Assignment 使用每个 Issue 的真实应交人数；转派追加审计版本。关闭任务固定结果/进度快照，重新打开生成新配置 revision。
5. 增加 `review_task_groups`：面向 Runs 合集的一个用户动作可以创建多个子 Campaign，但每个 Run 的模型复核进度仍独立。
6. 任务分配页按 Campaign 一张卡展示用途、数据集、Workset、目标 Run/合集、标签参考、进度、冲突和生命周期；Task detail 区分“来源历史”和“本任务交付”。当前独立页对 `task_kind='labeling'` 的排除需要移除，页面按 `purpose` 提供“Case 标注 / 判错复核”两个明确视图。
7. Case 标注分组增加“任务分配”入口，复用同一 Campaign 管理页并固定 `purpose=labeling`；支持进度、人员工作量、转派、冲突/裁决状态和审计历史。Case 标注页内仍保留快捷创建与任务筛选。
8. Case 标注分组增加“标注分析”入口。第一版复用并扩展现有 `/api/labeling/clusters`：除 GT→结果混淆对和 scenario 外，统计期望输出、GT 关系、Scene/Trigger/Egress Tags、证据缺口、排除提议、任务、标注人、冲突与裁决。`label_rationale` 提供全文搜索和明细导出，不自动把自由文本包装成稳定业务类别。
9. Case 标注讨论明确区分 Case 级公共频道与 Campaign 频道。任务页默认显示当前 Campaign + Case 公共讨论；跨任务历史作为分组只读参考，发言时必须选择目标频道。

验收：两个重叠 Campaign 不互相补完成度；Labeling 结果可供多个 Run 读取；关闭后成员集合和进度口径不会漂移；合集批量分配可以追溯到每个 Run 子任务；Case 标注任务可以在独立管理页转派和审计；“标注分析”与模型“原因聚类”的统计对象和文案不会混淆。

### S5：Runs 合集与统一评测工作区

1. 新增 `run_collections`、不可变 revision 和 members；编辑名称不改 revision，增删/排序成员生成新 revision。
2. 创建 `evaluation_context`，固定 Collection revision、Workset、GT/Label snapshot、评分策略和排除集合版本。
3. 合集页显示各 Run 覆盖率、混淆矩阵、相对基准 Run 的 P2F/F2P、缺预测，以及全部成员的 Issue 横向表。
4. 同一 Issue 只显示一份共享标签状态；每个 Run 单独显示 prediction、match 和 model-review 状态。
5. 从合集可创建共享 Labeling Campaign，或为选中的 Runs 创建 Model Review task group。
6. 现有两两 Run Comparison 保留为快捷视图，并可以“保存为合集”；它不再承担长期实验组织职责。

验收：合集成员更新不改变旧 evaluation；多个 Run 使用相同分母与参考快照；按某一 Run 选样的 Workset 明确标识选择偏差；导出包含 collection revision、Workset hash、snapshot ID 和评分契约。

### S6：历史兼容收尾

1. 逐范围将 legacy annotation 变为只读历史证据，业务统计停止依赖“最大 annotation ID”与 cross-Run fallback。
2. 保留旧 URL、annotation ID、Task ID、评论和附件映射；旧链接进入兼容详情并引导到当前 Label/Model Review 对象。
3. 清理 Gallery、Overview、Analysis、Trail preview 中重复且口径不同的 SQL，统一调用 Label projection、Model Review projection 和 Evaluation service。
4. 为未分类的 0206/0508 历史提供明确 `legacy_mixed` 展示；没有证据的内容不伪造为已标注、已复核或已裁决。
5. 每次切换保留影子对账和范围开关；回退只切读写入口，不删除新版本或历史证据。

最终完成条件：共享 Issue 标签、Run 级模型诊断、Campaign 进度和评测指标四套口径在页面、API、导出中一致；legacy fallback 不再决定任何新统计。

## 11. 验收场景与测试

| 场景 | 必须满足 |
|---|---|
| 单人 Case 保存标签，不填模型原因 | 标注已交；模型复核未因此完成 |
| 双人任务只完成一人 | 显示 1/2、保留证据；未作为一致结论进入 GT 更新 |
| 30% 交叉任务中的单人 Case | 按 1/1 完成，不错误等待第二人 |
| 两人标签相冲突，第三个 writer 不在分配内 | 可以显式裁决；人员完成数仍为原来的 2/2 |
| 裁决后又保存普通 Review/评论 | 裁决仍有效；历史意见可见 |
| 裁决时源记录或前一裁决被并发更新 | 409；无半条裁决、无漏清理的新附件，草稿保留 |
| 两个裁决者同时确认 | 只有基于当前版本的一次成功；另一人重新读取，不以提交时间解决 |
| 源标注之后有新版本/转派 | 相关裁决需重新确认；无关任务和模型原因修改不触发 |
| 同一 Issue 在任务 A 已交、任务 B 未交 | B 保持未交；独立进度及来源正确 |
| 非任务成员普通保存 | 保留已发布修复，无 403；不计入任务人员提交 |
| 从 Run A 筛 150 个 Case 标注，再用 Run B 对照 | 工作集固定；来源 A 可追溯；B 使用明确的相同标签快照 |
| Run A 的 Split 标注与 Run B/rand10 重叠 | 两边显示相同 Issue 标签状态；Run B 不继承 Run A 的模型原因、reviewer 或完成度 |
| 同一 Issue 的两个标注任务得到相同标签 | 共享状态为 resolved，并列出两个来源；不重复计算为两个 Issue |
| 同一 Issue 的两个标注任务得到不同标签 | 所有 Run 视图显示 source conflict；任何一个任务都不能靠时间戳覆盖另一个 |
| Review 发现 GT 错误，仅保存期望输出 | 生成 GT 修正提议；模型原因不强制填、不自动判完成 |
| GT 更新后模型与新 GT 一致 | 新比较可变为 MATCH；旧评测/诊断内容保持可追溯 |
| 多任务对同 Issue 给出不同期望输出 | 导出前提示冲突，不按最大 ID 或行顺序选择 |
| 导出后只有一部分 Trail 值变化 | 逐条核对，未变化部分继续待核对 |
| 缺 GT、缺预测、真实卡住 Stage1 输出 | 沿用现有标签/比较契约，分别报告覆盖与分母 |
| 旧附件被新裁决引用，用户尝试删除源记录 | 不丢失证据；返回明确依赖说明或使用审计撤回 |
| 新旧草稿、附件异步上传后切换 Run/Task | 不串域、不清空其他范围草稿、不错误自动跳转 |
| 旧混合 note/旧单人 Task 无法确定来源 | 展示为历史参考；不制造新提交、虚构裁决或补写时间 |
| 0522/0626/0821 的历史 Review note | 按用途映射原样成为标注依据；例外可追溯，不丢正文或批量留在错误的模型区域 |
| 标注页从任务、旧链接、刷新或浏览器返回进入 | 不显示模型结果和判错复核控件，payload 也不加载模型预测 |
| 数据集有完整 GT 但仅少数 Case 有工作台记录 | GT 覆盖与真实提交覆盖分别保留，不补造或丢失人工记录 |
| Runs 合集增加、删除或调整成员顺序 | 生成新 collection revision；旧 evaluation 的成员、分母和结果保持不变 |
| 从 Runs 合集创建模型复核任务 | 每个 Run 有独立子 Campaign/进度，共用 Workset 与参考快照；任务组可汇总但不合并完成状态 |
| 同一 Run 对两个 GT snapshots 评测 | 两个结果均可复现并显示参考版本；active GT 更新不改写旧结果 |
| 从 Case 标注分组进入任务分配 | 只显示 Labeling Campaign；可查看进度、转派和审计，不混入 Run Review 完成数 |
| 从 Case 标注分组进入标注分析 | 展示标签/GT/Tags/证据/冲突聚合；不把 label rationale 计入模型判错原因聚类 |
| Run A 的讨论与 Run B/rand10 重叠 Issue | 当前 Run 频道互相隔离；Issue/标注公共频道两边可见，并明确标出频道来源 |
| 指定 Labeling Campaign 打开讨论 | 显示当前 Campaign 与 Case 公共消息；其他 Campaign 仅按分组参考，不串回复树 |

数据库测试覆盖 SQLite 和 PostgreSQL，尤其验证多连接并发、约束、幂等和事务回滚；仅 SQLite 或 Python 进程锁测试不够。

前端回归覆盖 Enter/Shift+Enter、失败保留草稿、上传后台成功/失败、跨页切 Case、URL 恢复、同页保存与媒体不重载。浏览器验证至少走通一条标注路径、一条判错中 GT 修正路径和一次冲突裁决。

每个 schema/API 阶段运行云端完整测试；发布使用统一 exact-SHA deployer 的完整套件和隔离灰度。静态资源变更同步更新 index、loader、frontend contract 和 base-path contract 的缓存版本。

## 12. 发布、迁移与回退

- 新 schema 用增量 migration，同步 SQLite 初始化；新增共享表纳入 change-revision/topic 通知。
- 发布前准备逻辑备份并验证可恢复；先影子读取和小范围启用，再切任务写入。
- 新表、触发器及约束可能超过现有 deployer 的严格增量 SQL 白名单。实施时先检查并设计对应 migration 门禁，不能把触发器/回填偷偷移入应用启动来绕过检查。
- 后台迁移有版本、断点、幂等键与对账报告；不能在每次应用启动时无条件扫描改写历史。
- 实验开关按能力/任务范围使用；业务模型不增加一批临时状态。某个范围启用新写入后，不再同时走旧 writer。
- 回退优先关闭新写入、保持可查看新版本的兼容读取能力。旧 SHA 不认识新表时，不能把“数据库保留了数据”声称为“旧 UI 完整支持新数据”。
- 新记录、附件和导出清单在回退时保留；删除 schema 或回写旧 annotation 不是默认回退手段。
- 已在 Trail 完成的标签更新属于外部事实，应用回滚不撤销它；下次同步继续以 Trail 为准。
- 0508 等数据集既有用途/来源约束由 Workset 继承，抽成子集或人工修正不会改变其数据集身份。

## 13. 本提案建议采用的默认选择

1. Trail 是正式 GT 来源；本地任务结果和裁决为候选，通过导出与同步闭环生效。
2. 两种任务目的、两个独立页面，复用全部可共用的 UI 组件；标注、诊断分别保存。
3. Run 可作为选样来源；任务的 Case 集合与筛选快照冻结，人员转派单独留历史，Run 诊断明确隔离。
4. writer/admin 都能裁决，任务成员身份不作为裁决资格。
5. 单人修正允许在导出预览批量确认；多人冲突先显式裁决；已裁决结果无需额外管理员审批。
6. 任务可逐 Case 产出、分批导出，不等整批关闭。
7. 暂不实现严格双盲、跨 Run 自动复用模型原因或自动写 Trail GT；Runs 合集只组织评测和任务，不改变这三条边界。
8. 正式指标按固定参考版本计算；GT 待复核作为可见争议，不能静默改变分母。
9. 下一轮先交付 S1 跨 Run 共享标签投影；随后按 S2 快照、S3 模型复核、S4 Campaign、S5 Runs 合集推进。
10. 0522/0626/0821 默认迁到标注区，原 Review note 作为标注依据；0206/0508 保留并按批次核对模型复核用途。
11. Runs 合集成员版本不可变；一次正式评测固定 Collection revision、Workset、标签快照与评分策略。
