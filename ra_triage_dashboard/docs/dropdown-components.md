# 下拉组件约定与检查

所有产品可见的单选使用共享 `.ui-select`（`populateUiSelect` / `bindUiSelect`）。
保留原生 `<select>` 仅用于值和 change 事件，不显示浏览器原生菜单。
多选继续使用共享 `.multi-filter`，Review 标签使用已有 Review 下拉组件。

`enhanceDashboardSelects(root)` 初始化普通单选，包括没有 ID 的动态行；已有
`.ui-select-native` / `.gateway-model-native-select` 自定义组件由各自 renderer 管理，
不会被再次包裹。不要给未实现自定义界面的普通 select 添加这些类。

`observeDashboardSelects()` 在 bootstrap 注册一次，处理动态插入、选项文本及
禁用/隐藏状态变更。它只处理受影响的 select；不因 Gallery 图片、视频时间等
无关更新扫描或重建全部控件。它不会观测 JavaScript `.value` 属性赋值；renderer
在设置最终值后须调用 `enhanceNativeUiSelect(select)` 或批量增强同步显示。

增强保留原有 option 节点、空值、元数据、选中值及 change 事件契约；不触发业务
提交。相同内容的刷新不重建选项，保留已打开下拉的焦点。隐藏和禁用同步到可见
组件，禁用时关闭已打开菜单。键盘事件不应穿透到视频播放/切帧快捷键。

2026-10-21 检查覆盖静态页面的 76 个 select 和动态模板的 15 个 select 定义。
此前 40 个静态和 9 个动态定义未增强；统一入口补齐覆盖。已有 32 个自定义定义
和 10 个显式增强定义保留原行为。此计数是源码定义数量，动态行实例数随数据变化。

验证入口：

```sh
python3 -m unittest discover -s ra_triage_dashboard/tests -p 'test_frontend*.py' -q
node ra_triage_dashboard/tests/dropdown_components.cjs
```

第二项需要 Playwright 和 Chromium。它使用真实页面 DOM、CSS 和组件源文件，
验证静态覆盖、已有组件保持、键盘选择、选项刷新、空值与原节点保留、禁用/隐藏、
动态权限/视频行、弹窗、手机边界及多选连续操作；不访问 API 或提交业务表单。
可设置 `DROPDOWN_REPORT_DIR` 保存隔离组件预览截图；截图不代表线上登录态验收。


## Review status Escape behavior

The enhanced modelReviewStatusInput continues using bindUiSelect and the shared
native-select adapter. It opts into escapeFocus="blur": Escape closes the popup
and exits the focused control, including after 1/2/3 has chosen a status and the
popup is already closed. Arrow-focused options also exit without restoring focus
to the trigger. The chosen value and unsaved form draft remain intact; Escape
never submits or resets the Review. Other shared selects retain their established
Escape-to-trigger behavior. This applies in either language and at phone/desktop
widths; it does not introduce a separate status widget or hide focus outlines.
