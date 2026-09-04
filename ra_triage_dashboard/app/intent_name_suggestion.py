from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .model_catalog import (
    ModelCatalog,
    ModelCatalogError,
    model_gateway_chat_url,
    read_provider_api_key,
)
from .settings import Settings


MAX_RESPONSE_BYTES = 64 * 1024
MAX_SUGGESTION_CHARS = 80


class IntentNameSuggestionError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def rule_based_intent_name(
    dataset_labels: list[str],
    *,
    annotation_mode: str,
    case_count: int,
    overlap_ratio: float,
) -> str:
    releases = [str(label or "").split("·", 1)[0].strip() for label in dataset_labels]
    scope = "+".join(item for item in releases if item) or "Routing"
    count_suffix = f" {max(1, int(case_count))} Case"
    if annotation_mode == "full":
        return f"{scope} Routing 全量盲标{count_suffix}"[:MAX_SUGGESTION_CHARS]
    ratio = max(0, min(100, round(float(overlap_ratio) * 100)))
    return f"{scope} Routing 交叉{ratio}%复核{count_suffix}"[:MAX_SUGGESTION_CHARS]


def _normalized_suggestion(value: Any) -> str:
    if isinstance(value, list):
        value = "".join(
            str(item.get("text") or "")
            for item in value
            if isinstance(item, dict)
        )
    text = " ".join(str(value or "").replace("\u0000", "").split())
    text = re.sub(r"^(?:推荐(?:名称)?|实验名称)\s*[：:]\s*", "", text)
    text = text.strip("`'\"“”‘’。 ")
    if not text or len(text) > MAX_SUGGESTION_CHARS or any(ord(char) < 32 for char in text):
        raise IntentNameSuggestionError("模型没有返回可用的实验名称。")
    return text


def suggest_intent_name_with_llm(
    settings: Settings,
    model_catalog: ModelCatalog,
    *,
    fallback: str,
    dataset_labels: list[str],
    annotation_mode: str,
    case_count: int,
    overlap_ratio: float,
    overlap_reviewers: int,
    member_count: int,
    draft_name: str = "",
) -> str:
    selected = model_catalog.resolve(settings.ra_model_default_id, provider_id="kylin")
    api_key = read_provider_api_key(settings, "kylin")
    chat_url = model_gateway_chat_url(settings, "kylin")
    prompt = (
        "请为意图标注实验生成一个简洁、可检索的中文名称。只返回名称，不要解释，不超过40个字符。\n"
        f"数据集：{', '.join(dataset_labels)}\n"
        f"模式：{'全量盲标' if annotation_mode == 'full' else '交叉盲标'}\n"
        f"Case数量：{case_count}\n交叉比例：{round(overlap_ratio * 100)}%\n"
        f"每Case标注人数：{overlap_reviewers}\n成员数：{member_count}\n"
        f"用户当前草稿：{draft_name or '无'}\n"
        "如果用户提供了草稿，请在保留其核心含义的前提下优化；不要原样重复冗长或含糊的草稿。\n"
        f"规则名称参考：{fallback}"
    )
    body = json.dumps(
        {
            "model": selected["resolved_model_id"],
            "messages": [
                {"role": "system", "content": "你负责为内部数据标注实验命名。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 64,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        chat_url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apikey": api_key,
        },
    )
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=12) as response:
            if response.status != 200:
                raise IntentNameSuggestionError("模型名称推荐暂不可用。")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise IntentNameSuggestionError("模型名称推荐暂不可用。") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise IntentNameSuggestionError("模型名称推荐响应过大。")
    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise IntentNameSuggestionError("模型名称推荐响应格式非法。") from exc
    return _normalized_suggestion(content)
