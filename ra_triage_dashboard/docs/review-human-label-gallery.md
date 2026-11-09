# Review gallery shared human result

判错复核卡片在标题行右侧展示“人工”小字和当前人工类别，紧邻原共享标注/GT
关系徽标。复用 `.issue-label-pair`、`labelBadge` 和原 GT 关系组件；不增加冒号，
不改变 MATCH/MISMATCH（模型与所选 GT 的关系）的含义。

人工类别仅来自列表已有 `item.label_state` 的共享 Issue 投影。只有 `resolved`
且 `expected_output` 是合法三分类时展示类别；未标注、待补齐、分歧、过期裁决
展示状态，不回退到模型 Review、模型输出、顶层旧标注或任意单人提交。
普通判错和联合复核使用同一结果。联合复核编辑与保存仍走现有问题标注链路；
共享投影及图库 signature 已包含结果与来源修订，沿用现有保存后和协作刷新。
此改动不增加独立人工结果存储，不修改 GT、任务成员或 API 权限。

整行以文字基线对齐 Issue ID、人工小字、类别和 GT 关系文字；类别徽标以9px、
1.35行高匹配原关系徽标高度，原 GT 徽标声明不变。窄屏允许右侧整组换行，
以透明点击区域提供至少44px触控目标，不扩大可见 GT 徽标。
新增状态和字段同时提供中英文本，保留现有深浅主题。

The Review gallery shows the current shared Human conclusion beside the existing
GT-relation control in both review modes. It reads only the resolved shared Issue
projection; unresolved or invalid values remain explicit states. Existing Case
labeling edits, save reconciliation and collaboration refresh own the result.
Model/GT comparison remains independent. Typography uses baseline alignment and
preserves the GT chip's visual styling, including on narrow screens.

Preview acceptance:1920×1080 five-column layout and16 combinations of1920/1440/
390/320px,Chinese/English,dark/light passed using actual card renderer/styles and
local illustrative records. Desktop viewport checks are not physical-phone or
signed-in production write acceptance. See reports/review_human_label_preview_20261109/.
