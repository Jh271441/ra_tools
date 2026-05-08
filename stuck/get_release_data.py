def calc_metrics(tp, fn, fp, irrelevant=0):
    """
    tp         - 模型TP：自触发正确 / 正确触发
    fn         - 模型FN：人工触发漏检
    fp         - 模型FP：误触发
    irrelevant - 无关issue（人工触发误触发，不计入precision）
    """
    trigger_count = tp + fp           # 模型触发数
    precision = tp / (tp + fp) * 100  # 准确率
    recall    = tp / (tp + fn) * 100  # 召回率

    print(f"触发数：{trigger_count}")
    print(f"准确率：{precision:.2f}%")
    print(f"召回率：{recall:.2f}%")
    print(f"  TP={tp}, FN={fn}, FP={fp}, 无关issue={irrelevant}")

# 填入你的数据
calc_metrics(
    tp=570,
    fn=302,
    fp=269,
    irrelevant=33,
)

calc_metrics(
    tp=438,
    fn=229,
    fp=284,
    irrelevant=33,
)