# Review 标签与媒体快捷键

## 行为约定

Review 和问题标注详情中的标签多选下拉展开时，媒体快捷键继续有效：

- Space 播放/暂停；←/→ 跳转或切帧；B/C/V 切换媒体。
- Shift+C 直达 Camera 视频，V 返回上次选择的原始/局部 BEV 视频，C 仍切换到 Camera 图片；Shift+V 切换原始/局部 BEV；O 切回原始 BEV；G 展开/收起规划约束；F 展开媒体。
- Camera 的视频源记忆与 BEV 选择分开；Shift+C 后按 V 能返回 BEV，并保留该播放器的时间、倍速和播放/暂停状态。详情与当前 Issue 的展开弹窗共享 BEV 选择，切换 Issue 后重置；缺少 BEV 时保留当前视图并提示，不回退到 Camera。
- Shift+C opens Camera video; V returns to the last original/closeup BEV choice without Camera replacing that choice. The current Issue detail and expanded dialog share this choice; switching Issues resets it. Source changes preserve the player's position, rate and play/pause state. Missing BEV keeps the current view and shows localized feedback.
- Shift+C 在 Review、问题标注详情及展开媒体中复用现有视频源切换，保留播放位置、倍速及播放/暂停状态。当前 Issue 无 Camera 视频时保留当前视图，并显示中英文提示；输入、IME、重复按键和修饰键组合不触发。
- 0 回到 t0。若展开组里有可见且启用的 0 标签快捷键，该标签优先。
- 展开的标签或缺失信息组用 `1–9、0、-、=` 切换键位 1–12，用 `Shift` 加同一排键切换键位 13–24。徽标用 `⇧` 表示 Shift。上下箭头定位选项，Enter 保存，Esc 关闭。
- 键位按目录 ID 保存。初次分配沿用可见选项顺序，改名保留原键位，删除释放的键位可分给其他选项。标签移动到另一组时按新组的空位分配。
- 超出键位容量的组可按名称搜索。搜索框中 Enter 切换唯一匹配项，↓ 聚焦匹配结果。关闭菜单会清空搜索，保留已选标签。
- Space 不再切换标签复选框或开关原生 details；播放动作只执行一次。
- 播放和跳转复用实际媒体按钮动作，保持下拉展开和标签选择；媒体切换保留已有标签下拉焦点。展开媒体或规划约束时，新弹层取得自身所需焦点。
- 普通文本、搜索、说明、select、增强单选、contenteditable、输入法组合输入仍保留各自键盘操作。未开放任意输入控件的媒体快捷键。

## Esc 与焦点

Esc 由最内层控件先处理：打开的单选、规划约束和原生模态框保留自身关闭语义；底层标签下拉不会抢先处理同一次 Esc。没有更高层控件接管时，Esc 收起标签下拉并释放详情中的输入、按钮、链接或可聚焦媒体表面的焦点。Review/问题标注详情及展开媒体的共享单选，Esc 同时释放单选焦点。

原生模态框关闭后按浏览器规则恢复打开按钮的焦点；再次 Esc 可离开“历史”等按钮，随后 E 等快捷键可直接使用。输入法组合输入、修饰键和已消费事件不会被焦点释放逻辑接管。未提交的文字和标签选择不会因 Esc 被清空或保存。

## 标签说明 / Tag descriptions

Review 与问题标注详情共用标签说明浮层。悬停标签或用键盘聚焦复选框时，显示共享目录中保存的标签名和 `hint` 原文；未填写时显示“暂无说明 / No description yet”。通过现有 `⋯ → 查看说明 / View description` 菜单也可打开，供触屏使用。查看或选择说明文字不切换标签，不产生 API 写入。目录修改和运行时语言切换同步说明，保留原复选框与选择。

浮层复用共享 info 组件及可见视口定位，说明按纯文本显示并支持长内容换行/滚动。它不消费标签下拉的 Esc：同一次按键关闭下拉并释放焦点；数字标签键、视频空格/左右和 Issue 切换继续按原规则处理。关闭下拉同时清理其说明浮层。

## 验证入口

`tests/test_review_tag_shortcut_slots.py` 覆盖固定键位、删除补位、组间独立、并发写入及数字行按键解析。共享键位保存在 Dashboard 数据目录的 `review_tag_shortcuts.json`，其中只有目录 ID 和键位编号。编辑目录的响应返回 `shortcut_slot`，历史标签和超出容量的标签为 `null`。

`tests/test_review_media_shortcuts.py` 覆盖媒体输入保护、复选框放通、数字 0 优先级、激活动作范围及 Esc 的层级/页面/IME 保护；`tests/test_review_shortcuts.py` 保留标签数字选择和 Enter 保存回归。

实际浏览器集成入口（只使用本地媒体与合成 API）：

```sh
REVIEW_MEDIA_TEST_CLIP=/path/to/local.mp4 \
REVIEW_MEDIA_TEST_POSTER=/path/to/local.jpg \
python3 ra_triage_dashboard/tests/review_media_shortcuts_browser.py
```

覆盖实际页面模块、播放器、原生模态框、共享单选及 320/390/1440px、中文/英文、深色/浅色组合。浏览器缩小视口属于桌面响应式测试，不代表真机或原生手机软键盘验收。

`python3 ra_triage_dashboard/tests/review_tag_hints_browser.py` 使用实际页面模块与合成目录检查说明浮层、菜单入口、空说明、纯文本转义、语言切换保留节点、长文案边界及 Esc/视频操作，不访问生产或写入业务数据。
