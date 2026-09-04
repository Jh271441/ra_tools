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
TOKEN_SERVICE_NAME_MODEL_PREFERENCE = (
    "aliyun/Qwen3.6-Flash",
    "aliyun/Qwen3.5-Plus",
    "aliyun/Qwen3-Next-80B-A3B-Instruct",
)


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
    overlap_reviewers: int = 2,
    member_count: int = 2,
    label_scope: str = "routing",
) -> str:
    releases = [str(label or "").split("·", 1)[0].strip() for label in dataset_labels]
    scope = "+".join(item for item in releases if item) or "Routing"
    count_suffix = f" {max(1, int(case_count))} Case"
    intent_name = {
        "routing": "Routing",
        "lane_change": "变道意图",
        "all": "Routing+变道意图",
    }.get(label_scope, "Routing+变道意图")
    if annotation_mode == "full":
        return f"{scope} {intent_name} 全量盲标{count_suffix}"[:MAX_SUGGESTION_CHARS]
    if member_count < 2 or overlap_reviewers < 2 or overlap_ratio <= 0:
        mode = "单人盲标" if member_count == 1 else "分工盲标"
        return f"{scope} {intent_name} {mode}{count_suffix}"[:MAX_SUGGESTION_CHARS]
    ratio = max(0, min(100, round(float(overlap_ratio) * 100)))
    return f"{scope} {intent_name} 交叉{ratio}%复核{count_suffix}"[:MAX_SUGGESTION_CHARS]


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


def _validate_contextual_suggestion(
    suggestion: str,
    *,
    dataset_labels: list[str],
    annotation_mode: str,
    case_count: int,
    overlap_ratio: float,
    overlap_reviewers: int,
    member_count: int,
    label_scope: str = "routing",
) -> str:
    releases = [str(label or "").split("·", 1)[0].strip() for label in dataset_labels]
    required_releases = [release for release in releases if release]
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", suggestion))
    has_scope = all(release in suggestion for release in required_releases)
    has_routing = "routing" in suggestion.lower() or "路由" in suggestion
    has_intent_scope = {
        "routing": has_routing,
        "lane_change": "变道" in suggestion,
        "all": has_routing and "变道" in suggestion,
    }.get(label_scope, False)
    has_count = str(max(1, int(case_count))) in suggestion
    if annotation_mode == "full":
        has_mode = "全量" in suggestion and "盲标" in suggestion
    elif member_count > 1 and overlap_reviewers > 1 and overlap_ratio > 0:
        ratio = str(max(0, min(100, round(float(overlap_ratio) * 100))))
        has_mode = ratio in suggestion and ("交叉" in suggestion or "复核" in suggestion)
    elif member_count == 1:
        has_mode = "单人" in suggestion and "盲标" in suggestion and "交叉" not in suggestion
    else:
        has_mode = "分工" in suggestion and "盲标" in suggestion and "交叉" not in suggestion
    if not (has_chinese and has_scope and has_intent_scope and has_count and has_mode):
        raise IntentNameSuggestionError("模型名称缺少实验关键信息。")
    return suggestion


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
    label_scope: str = "routing",
) -> str:
    provider_id = "kylin"
    try:
        selected = model_catalog.resolve(settings.ra_model_default_id, provider_id=provider_id)
    except ModelCatalogError:
        provider_id = "tokenservice"
        try:
            snapshot = model_catalog.list_models(
                allow_stale=True,
                provider_id=provider_id,
            )
            model_ids = {str(item.get("id") or "") for item in snapshot.get("models", [])}
            requested_model = next(
                (item for item in TOKEN_SERVICE_NAME_MODEL_PREFERENCE if item in model_ids),
                str(snapshot.get("default_model_id") or ""),
            )
            if not requested_model:
                raise ModelCatalogError(503, "TokenService 当前没有可用的名称生成模型。")
            selected = model_catalog.resolve(requested_model, provider_id=provider_id)
        except ModelCatalogError as tokenservice_error:
            raise IntentNameSuggestionError("模型名称推荐暂不可用。") from tokenservice_error
    api_key = read_provider_api_key(settings, provider_id)
    chat_url = model_gateway_chat_url(settings, provider_id)
    if annotation_mode == "full":
        mode_label = "全量盲标"
    elif member_count > 1 and overlap_reviewers > 1 and overlap_ratio > 0:
        mode_label = f"交叉{round(overlap_ratio * 100)}%复核"
    elif member_count == 1:
        mode_label = "单人盲标"
    else:
        mode_label = "分工盲标"
    prompt = (
        "请为意图标注实验生成一个简洁、可检索的中文名称。只返回名称，不要解释，不超过40个字符。\n"
        f"数据集：{', '.join(dataset_labels)}\n"
        f"模式：{mode_label}\n"
        f"标注维度：{ {'routing': 'Routing 意图', 'lane_change': '变道意图', 'all': 'Routing 与变道意图'}[label_scope] }\n"
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
            **(
                {"Authorization": f"Bearer {api_key}"}
                if provider_id == "tokenservice"
                else {"apikey": api_key}
            ),
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
    return _validate_contextual_suggestion(
        _normalized_suggestion(content),
        dataset_labels=dataset_labels,
        annotation_mode=annotation_mode,
        case_count=case_count,
        overlap_ratio=overlap_ratio,
        overlap_reviewers=overlap_reviewers,
        member_count=member_count,
        label_scope=label_scope,
    )
