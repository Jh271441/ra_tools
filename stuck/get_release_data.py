def calc_metrics(tp, fn, fp, irrelevant=0, version="", cztl_sources=None):
    """
    tp           - 模型TP：自触发正确 / 正确触发
    fn           - 模型FN：人工触发漏检
    fp           - 模型FP：误触发
    irrelevant   - 无关issue
    cztl_sources - CZ_TL来源列表，每项: {"name": str, "count": int, "precision": float(0~1)}
    """
    cztl_sources = cztl_sources or []

    for src in cztl_sources:
        if src.get("precision") is None:
            continue
        tp += src["count"] * src["precision"]
        fp += src["count"] * (1 - src["precision"])

    trigger_count = tp + fp
    precision = tp / (tp + fp) * 100
    recall    = tp / (tp + fn) * 100

    print(f"版本号：{version}")
    for src in cztl_sources:
        prec_str = f"{src['precision']*100:.2f}%" if src.get("precision") is not None else "未知"
        print(f"  [{src['name']}] CZTL数量：{src['count']}  准确率：{prec_str}")
    print(f"触发数：{trigger_count:.0f}")
    print(f"准确率：{precision:.2f}%")
    print(f"召回率：{recall:.2f}%")
    print(f"  TP={tp:.1f}, FN={fn}, FP={fp:.1f}, 无关issue={irrelevant}")
    print()


# ──────────────────────────────────────────────────────────────
# 各版本数据
# ──────────────────────────────────────────────────────────────

calc_metrics(
    version="gen4-release-20260327",
    tp=438, fn=229, fp=284, irrelevant=26,
    cztl_sources=[
        {"name": "Stuck",         "count": 199, "precision": 0.9950},
        {"name": "TidalFlowLane", "count": 15,  "precision": 0.3333},
        {"name": "kEOL",          "count": 10,  "precision": 1.0000},
        {"name": "CorePlanner",   "count": 29,  "precision": None},   # 图中未标注，待确认
    ],
)

calc_metrics(
    version="gen4-release-20260403",
    tp=570, fn=302, fp=269, irrelevant=33,
    cztl_sources=[
        {"name": "Stuck",         "count": 324, "precision": 0.9846},
        {"name": "TidalFlowLane", "count": 12,  "precision": 0.0833},
        {"name": "kEOL",          "count": 18,  "precision": 0.6667},
        {"name": "CorePlanner",   "count": 33,  "precision": 0.6667},
    ],
)

calc_metrics(
    version="gen4-release-20260410",
    tp=696, fn=293, fp=354, irrelevant=52,
    cztl_sources=[
        {"name": "Stuck",         "count": 525, "precision": 0.9673},
        {"name": "TidalFlowLane", "count": 9,   "precision": 0.2222},
        {"name": "kEOL",          "count": 17,  "precision": 0.8667},
        {"name": "CorePlanner",   "count": 42,  "precision": 0.7381},
    ],
)

calc_metrics(
    version="gen4-release-20260417",
    tp=582, fn=254, fp=359, irrelevant=53,
    cztl_sources=[
        {"name": "Stuck",         "count": 353, "precision": 0.9479},
        {"name": "TidalFlowLane", "count": 16,  "precision": 0.0769},
        {"name": "kEOL",          "count": 11,  "precision": 1.0000},
        {"name": "CorePlanner",   "count": 55,  "precision": 0.6000},
    ],
)
