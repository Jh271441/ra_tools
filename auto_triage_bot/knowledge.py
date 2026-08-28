from __future__ import annotations

import hashlib
from pathlib import Path


KNOWLEDGE_PATH = Path(__file__).with_name("knowledge") / "ra_triage.md"


def load_knowledge() -> tuple[str, str]:
    text = KNOWLEDGE_PATH.read_text(encoding="utf-8").strip()
    version = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return text, version


def deterministic_answer(question: str) -> str:
    normalized = question.strip().lower()
    if normalized in {"help", "/help", "帮助", "你会什么", "怎么用"}:
        return (
            "我可以解释 RA Auto Triage 三分类，也可以结合看板中的 Issue、默认/指定模型 Run 和该 Run 的最新 Review 回答。\n\n"
            "用法：发送 Issue ID 或看板链接，再写问题；如需指定模型，请保留链接里的 `run=`，或写 `run: <id>`。"
        )
    if "正确触发" in question and "无需协助" in question:
        return (
            "两者都要求触发时确实存在卡住候选。区别看触发后的演化：约束自行解除、前车驶离或主系统自主恢复，且没有强人工协助证据，是“无需协助”；阻塞持续，或依赖 waypoint、SWAG、方向键、倒车、MRC 等协助脱困，是“正确触发”。"
        )
    if "误触发" in question and any(word in question for word in ("什么", "怎么", "定义", "判断")):
        return (
            "“误触发”表示触发时并不是真正卡住，例如红灯、排队、拥堵跟车、让行、道闸等待、正常泊入泊出或掉头中的停顿。判定时先看触发时是否真卡；如果不是真卡，后续即使前车驶离，也仍是误触发。"
        )
    return ""
