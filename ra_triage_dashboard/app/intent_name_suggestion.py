from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .model_catalog import (
    ModelCatalog,
    model_gateway_chat_url,
    read_provider_api_key,
)
from .settings import Settings


MAX_RESPONSE_BYTES = 64 * 1024
MAX_SUGGESTION_CHARS = 80
INTENT_NAME_MODEL_ID = "Qwen3.8-27B/Qwen3.8-27B"


class IntentNameSuggestionError(RuntimeError):
    def __init__(self, message: str, *, reason: str = "invalid_output") -> None:
        super().__init__(message)
        self.reason = reason


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


def _allocation_mode_label(
    *, reviewers_per_issue: int, overlap_ratio: float, member_count: int
) -> str:
    reviewers = max(1, int(reviewers_per_issue))
    members = max(0, int(member_count))
    if members <= 0:
        return "待选人员"
    if reviewers > 1 and members > 1 and overlap_ratio > 0:
        ratio = max(0, min(100, round(float(overlap_ratio) * 100)))
        return f"{reviewers}人交叉{ratio}%复核"
    if reviewers == 1:
        return "单人均分" if members == 1 else f"{members}人均分"
    return f"{reviewers}人复核"


def rule_based_assignment_name(
    dataset_labels: list[str],
    *,
    assignment_kind: str,
    case_count: int,
    reviewers_per_issue: int,
    overlap_ratio: float,
    member_count: int,
    workflow_mode: str = "",
    run_name: str = "",
    comparison: str = "all",
) -> str:
    releases = [str(label or "").split("·", 1)[0].strip() for label in dataset_labels]
    scope = "+".join(item for item in releases if item) or "Dataset"
    mode = _allocation_mode_label(
        reviewers_per_issue=reviewers_per_issue,
        overlap_ratio=overlap_ratio,
        member_count=member_count,
    )
    if assignment_kind == "case_labeling":
        subject = "Case标注"
        run_part = ""
        comparison_part = ""
    else:
        subject = (
            "联合复核"
            if workflow_mode == "model_review_and_case_label"
            else "判错复核"
        )
        run_part = " ".join(str(run_name or "").split("·", 1)[0].split())[:28]
        comparison_part = (
            str(comparison or "").strip().upper()
            if str(comparison or "").strip().lower() not in {"", "all"}
            else ""
        )
    suffix = " ".join(
        item
        for item in (
            subject,
            comparison_part,
            mode,
            str(max(1, int(case_count))),
            "Case",
        )
        if item
    )
    prefix = " ".join(item for item in (scope, run_part) if item)
    available = max(0, MAX_SUGGESTION_CHARS - len(suffix) - 1)
    return f"{prefix[:available]} {suffix}".strip()[:MAX_SUGGESTION_CHARS]


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


def _validate_assignment_suggestion(
    suggestion: str,
    *,
    fallback: str,
    dataset_labels: list[str],
    assignment_kind: str,
    case_count: int,
    reviewers_per_issue: int,
    overlap_ratio: float,
    member_count: int,
    workflow_mode: str,
    run_name: str,
    comparison: str,
) -> str:
    releases = [str(label or "").split("·", 1)[0].strip() for label in dataset_labels]
    required_releases = [release for release in releases if release]
    has_scope = all(release in suggestion for release in required_releases)
    has_count = str(max(1, int(case_count))) in suggestion
    expected_mode = _allocation_mode_label(
        reviewers_per_issue=reviewers_per_issue,
        overlap_ratio=overlap_ratio,
        member_count=member_count,
    )
    if expected_mode == "待选人员":
        has_mode = "待选" in suggestion
    elif "交叉" in expected_mode:
        ratio = str(max(0, min(100, round(float(overlap_ratio) * 100))))
        has_mode = (
            ratio in suggestion
            and str(max(1, int(reviewers_per_issue))) in suggestion
            and ("交叉" in suggestion or "复核" in suggestion)
        )
    elif expected_mode == "单人均分":
        has_mode = "单人" in suggestion and "交叉" not in suggestion
    elif expected_mode.endswith("人均分"):
        has_mode = expected_mode in suggestion
    else:
        has_mode = expected_mode in suggestion or (
            str(max(1, int(reviewers_per_issue))) in suggestion
            and "复核" in suggestion
            and "交叉" not in suggestion
        )
    if assignment_kind == "case_labeling":
        has_subject = "Case" in suggestion and "标注" in suggestion
    elif workflow_mode == "model_review_and_case_label":
        has_subject = "联合" in suggestion or ("判错" in suggestion and "Case" in suggestion)
    else:
        has_subject = "判错" in suggestion and "复核" in suggestion
    run_hint = " ".join(str(run_name or "").split("·", 1)[0].split()).split(" ", 1)[0][:16]
    has_run = not run_hint or run_hint.lower() in suggestion.lower()
    normalized_comparison = str(comparison or "").strip().upper()
    has_comparison = (
        normalized_comparison in {"", "ALL"}
        or normalized_comparison in suggestion.upper()
    )
    if not (
        re.search(r"[\u4e00-\u9fff]", suggestion)
        and has_scope
        and has_count
        and has_mode
        and has_subject
        and has_run
        and has_comparison
    ):
        raise IntentNameSuggestionError("模型名称缺少实验关键信息。")
    return suggestion


def _request_name_completion(
    settings: Settings,
    *,
    prompt: str,
    system_prompt: str,
    timeout: int = 8,
    max_tokens: int = 64,
) -> str:
    provider_id = "kylin"
    api_key = read_provider_api_key(settings, provider_id)
    chat_url = model_gateway_chat_url(settings, provider_id)
    body = json.dumps(
        {
            "model": INTENT_NAME_MODEL_ID,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
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
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
            if response.status != 200:
                raise IntentNameSuggestionError("模型名称推荐暂不可用。", reason="unavailable")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
        raise IntentNameSuggestionError(
            "模型名称推荐暂不可用。", reason="timeout" if timed_out else "unavailable"
        ) from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise IntentNameSuggestionError("模型名称推荐响应过大。")
    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise IntentNameSuggestionError("模型名称推荐响应格式非法。") from exc
    return _normalized_suggestion(content)


def suggest_intent_name_with_llm(
    settings: Settings,
    _model_catalog: ModelCatalog,
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
        f"规则名称参考：{fallback}\n"
        "请在保留所有关键信息的前提下优化措辞，不要与规则名称完全相同。"
    )
    return _validate_contextual_suggestion(
        _request_name_completion(
            settings,
            prompt=prompt,
            system_prompt="你负责为内部数据标注实验命名。",
        ),
        dataset_labels=dataset_labels,
        annotation_mode=annotation_mode,
        case_count=case_count,
        overlap_ratio=overlap_ratio,
        overlap_reviewers=overlap_reviewers,
        member_count=member_count,
        label_scope=label_scope,
    )


def suggest_assignment_name_with_llm(
    settings: Settings,
    _model_catalog: ModelCatalog,
    *,
    fallback: str,
    dataset_labels: list[str],
    assignment_kind: str,
    case_count: int,
    reviewers_per_issue: int,
    overlap_ratio: float,
    member_count: int,
    workflow_mode: str = "",
    run_name: str = "",
    comparison: str = "all",
    draft_name: str = "",
) -> str:
    subject = "Case标注" if assignment_kind == "case_labeling" else (
        "联合复核" if workflow_mode == "model_review_and_case_label" else "判错复核"
    )
    allocation = _allocation_mode_label(
        reviewers_per_issue=reviewers_per_issue, overlap_ratio=overlap_ratio, member_count=member_count
    )
    required = [str(label).split("·", 1)[0].strip() for label in dataset_labels]
    required.extend([subject, allocation, str(case_count), "Case"])
    if assignment_kind == "model_review":
        run_hint = " ".join(str(run_name).split("·", 1)[0].split()).split(" ", 1)[0][:16]
        if run_hint:
            required.append(run_hint)
        if str(comparison).strip().lower() not in {"", "all"}:
            required.append(str(comparison).strip().upper())
    prompt = (
        "请为内部任务分配实验生成一个简洁、可检索的中文名称。只返回名称，不要解释，不超过80个字符。\n"
        f"任务类型：{subject}\n"
        f"数据集：{', '.join(dataset_labels)}\n"
        f"Case数量：{case_count}\n"
        f"每Case人数：{reviewers_per_issue}\n"
        f"成员数：{member_count}\n"
        f"交叉比例：{round(overlap_ratio * 100)}%\n"
        f"工作流：{workflow_mode or 'case_labeling'}\n"
        f"模型Run：{run_name or '无'}\n"
        f"模型判断范围：{comparison or 'all'}\n"
        f"用户当前草稿：{draft_name or '无'}\n"
        f"规则名称参考：{fallback}\n"
        f"以下片段必须逐字保留：{json.dumps(required, ensure_ascii=False)}。\n"
        "分配方式使用给定片段，不要根据每Case人数改成单人。"
        "可以调整片段顺序或连接词，不得改变任务含义；规则名称已合适时允许原样返回。"
    )
    suggestion = _request_name_completion(
        settings,
        prompt=prompt,
        system_prompt="你负责为内部 Case 标注和模型复核任务命名。",
        timeout=15,
        max_tokens=128,
    )
    return _validate_assignment_suggestion(
        suggestion,
        fallback=fallback,
        dataset_labels=dataset_labels,
        assignment_kind=assignment_kind,
        case_count=case_count,
        reviewers_per_issue=reviewers_per_issue,
        overlap_ratio=overlap_ratio,
        member_count=member_count,
        workflow_mode=workflow_mode,
        run_name=run_name,
        comparison=comparison,
    )
