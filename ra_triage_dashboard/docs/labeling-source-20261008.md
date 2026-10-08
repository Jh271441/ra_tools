# 标注汇总来源与筛选栏对齐 · 2026-10-08

运行版本：235e8c909a26308db75c7817f89915b892a987d9；静态缓存551；数据库schema053不变。

- Review筛选栏增强select原有34/38px与其余32px混用，现统一32px；模式字段增加宽度，任务锁定提示不挤占控件基线。
- 汇总明细分成上下两层：Issue/期望输出/GT/状态及来源在上，依据/标签/原始意见在下。
- 只有一个“期望输出规则”Info入口，全部标注和任务范围使用完全相同的统一说明。
- 每个Case独立显示真实来源：Issue裁决、任务内裁决、多来源一致、多人一致、单人标注，未决时不显示旧结果来源。
- 来源可展开查看自己的任务ID、Run、作者、记录编号；Issue裁决展示Decision编号。
- 多来源一致中包含任务裁决时，不误称该任务裁决覆盖其它来源。主依据记录与最终来源区分。
- 新增expected_output_source描述已有投影；没有改变裁决规则、GT、导出、任务范围或权限。

验证：最终完整回归633 passed、5 skipped。首次门禁发现base-path测试仍写死旧cache，未切换源码；修正后通过。
只读冻结副本对照381条汇总记录，仅新增来源字段；去除该新增字段后，原业务返回、OpenAPI、GT候选、任务及评估契约完全相同。
浏览器验证1920px桌面每排所有控件top/height一致；390px无横向溢出，Info可完整操作。
cn32088467在全部范围显示3来源一致（含任务裁决），在172条历史任务范围显示任务内裁决jasperchen/记录2315；Info说明一致。
Issue裁决记录展开、原有任务范围切换和两层排版通过，控制台无错误。QA未提交真实标注、任务、GT或Trail写入。

证据：8786实验目录source-provenance-20261008-551-final/{before.json.gz,after.json.gz,tests.log,verified.json,release.json}。
本机截图：/Users/didi/workspace/ra_tools/reports/source_provenance_8786_20261008/。
回滚源码：e7f91757090d9a71b1ed8777bcbc34cd897bbbbc；保持DB/config不变，只恢复source_sha并重启原8786 Supervisor。
8785保持399072e331ee597e46bff1e60327c43889624960。发布后的本记录是纯文档提交。
