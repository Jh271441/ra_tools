# 自触发额外TP/FP（EOL、红绿灯等来源）
EXTRA = {
    "gen4-release-20260327": {"tp": 233, "fp": 23},
    "gen4-release-20260403": {"tp": 354, "fp": 33},
    "gen4-release-20260410": {"tp": 556, "fp": 37},
    "gen4-release-20260417": {"tp": 380, "fp": 55},
    "gen4-release-20260206": {"tp": 349, "fp": 3},
}


def calc_metrics(version, tp, fn, fp):
    extra = EXTRA.get(version, {"tp": 0, "fp": 0})
    tp_total = tp + extra["tp"]
    fp_total = fp + extra["fp"]

    precision = tp_total / (tp_total + fp_total) * 100
    recall    = tp_total / (tp_total + fn) * 100

    print(f"版本号：{version}")
    print(f"准确率：{precision:.2f}%  召回率：{recall:.2f}%")
    print(f"  TP={tp_total}, FN={fn}, FP={fp_total}  (额外 TP+{extra['tp']}, FP+{extra['fp']})")
    print()


# calc_metrics(version="gen4-release-20260327", tp=438, fn=229, fp=284)
# calc_metrics(version="gen4-release-20260403", tp=570, fn=302, fp=269)
# calc_metrics(version="gen4-release-20260410", tp=696, fn=293, fp=354)
# calc_metrics(version="gen4-release-20260417", tp=582, fn=254, fp=359)


calc_metrics(version="gen4-release-20260327", tp=441, fn=217, fp=241)
calc_metrics(version="gen4-release-20260403", tp=552, fn=305, fp=223)
calc_metrics(version="gen4-release-20260410", tp=666, fn=310, fp=296)
calc_metrics(version="gen4-release-20260417", tp=566, fn=259, fp=307)
calc_metrics(version="gen4-release-20260206", tp=475, fn=213, fp=475)
calc_metrics(version="gen4-release-20260206", tp=821, fn=253, fp=247)
