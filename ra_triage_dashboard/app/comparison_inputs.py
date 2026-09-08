"""Read-only provenance projection; never resolve inference paths as web assets."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from .sanitization import redact_sensitive_fields


EXTRA_INPUT_AXES = {
    'routing': {
        'label': 'Routing',
        'keys': ('routing_intent_frames', 'routing_intents', 'routing_intent'),
        'values': {
            'parking': '泊车', 'straight': '直行', 'left_turn': '左转',
            'right_turn': '右转', 'u_turn': '掉头',
            '泊车': '泊车', '直行': '直行', '左转': '左转', '右转': '右转', '掉头': '掉头',
        },
        'prompt_markers': ('routing', '路由意图'),
    },
    'lane_change': {
        'label': '自车变道',
        'keys': ('lane_change_intent_frames', 'lane_change_intents', 'lane_change_intent'),
        'values': {
            'lane_change': '变道', 'no_lane_change': '非变道',
            '变更车道': '变道', '保持车道': '非变道',
            '变道': '变道', '非变道': '非变道',
        },
        'prompt_markers': ('lane_change', '变道意图', '自车变道', '变道概率'),
    },
}


def _count_axis_value(value: Any, aliases: dict[str, str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    if isinstance(value, str):
        text = value.strip()
        if text in aliases:
            counts[aliases[text]] += 1
        else:
            for raw, label in aliases.items():
                prefix = r'(?<![\w])' if raw.isascii() else (r'(?<!非)' if raw == '变道' else '')
                match = re.search(rf'{prefix}{re.escape(raw)}\s*[:=：]?\s*(\d+)\s*帧?', text, re.I)
                if match:
                    counts[label] = max(counts[label], int(match.group(1)))
            if not counts:
                for token in re.findall(r'[A-Za-z_]+|[\u4e00-\u9fff]+', text):
                    if token in aliases:
                        counts[aliases[token]] += 1
        return counts
    if isinstance(value, list):
        for item in value:
            counts.update(_count_axis_value(item, aliases))
        return counts
    if isinstance(value, dict):
        direct = value.get('label') or value.get('intent') or value.get('value')
        if direct is not None:
            amount = value.get('count', 1)
            nested = _count_axis_value(direct, aliases)
            for label, count in nested.items():
                counts[label] += count * (int(amount) if isinstance(amount, int) and amount > 0 else 1)
            return counts
        for key, nested in value.items():
            if key in aliases and isinstance(nested, int) and nested >= 0:
                counts[aliases[key]] += nested
            elif key not in {'count', 'total', 'frame_count'}:
                counts.update(_count_axis_value(nested, aliases))
    return counts


def _probability_winner(value: str, aliases: dict[str, str]) -> str:
    candidates: list[tuple[float, str]] = []
    for raw in sorted(aliases, key=len, reverse=True):
        match = re.search(rf'{re.escape(raw)}\s*=\s*(0(?:\.\d+)?|1(?:\.0+)?)', value, re.I)
        if match:
            candidates.append((float(match.group(1)), aliases[raw]))
    return max(candidates, default=(0.0, ''))[1]


def extra_input_summary(raw: dict, extra: dict) -> dict[str, Any]:
    """Project only explicitly saved per-Case auxiliary model inputs."""
    raw = raw if isinstance(raw, dict) else {}
    extra = extra if isinstance(extra, dict) else {}
    containers = [extra, raw.get('model_extra', {}), raw]
    containers = [item for item in containers if isinstance(item, dict)]
    axes: dict[str, Any] = {}
    for axis, spec in EXTRA_INPUT_AXES.items():
        value = None
        source = ''
        for container_index, container in enumerate(containers):
            nested = container.get('extra_inputs')
            candidates = [nested] if isinstance(nested, dict) else []
            candidates.append(container)
            for candidate in candidates:
                for key in spec['keys']:
                    if key in candidate:
                        value = candidate[key]
                        source = f"saved.{container_index}.{key}"
                        break
                if source:
                    break
            if source:
                break
        counts = _count_axis_value(value, spec['values']) if source else Counter()
        if not source:
            prompt = ''
            for container in containers:
                prompt = container.get('prompt_text') or container.get('actual_prompt') or ''
                if isinstance(prompt, str) and prompt:
                    break
            if prompt:
                for line in prompt.splitlines():
                    folded = line.casefold()
                    if any(marker.casefold() in folded for marker in spec['prompt_markers']):
                        segment = line
                        if axis == 'routing' and re.search(r'routing\s*概率', line, re.I):
                            segment = re.split(r'routing\s*概率\s*[：:]', line, flags=re.I)[-1]
                        elif axis == 'lane_change' and '变道概率' in line:
                            segment = line.split('变道概率', 1)[-1].split('| Routing', 1)[0]
                        winner = _probability_winner(segment, spec['values'])
                        parsed = Counter({winner: 1}) if winner else _count_axis_value(segment, spec['values'])
                        if parsed:
                            counts.update(parsed)
                            source = 'actual_prompt'
        if source:
            axes[axis] = {
                'label': spec['label'],
                'status': 'available' if counts else 'partial',
                'frame_count': sum(counts.values()),
                'counts': dict(counts),
                'source': source,
            }
    return {'available': bool(axes), 'axes': axes}


def normalize_extra_input_filter(value: Any) -> dict[str, Any]:
    if value in (None, '', {}):
        return {'version': 1, 'run': 'candidate', 'relation': 'all', 'conditions': []}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError('额外输入筛选格式不合法。') from exc
    if not isinstance(value, dict) or value.get('version', 1) != 1:
        raise ValueError('不支持的额外输入筛选版本。')
    run = str(value.get('run') or 'candidate')
    relation = str(value.get('relation') or 'all')
    if run not in {'candidate', 'baseline', 'either'} or relation not in {'all', 'any'}:
        raise ValueError('额外输入筛选范围或关系不合法。')
    conditions = []
    for item in value.get('conditions') or []:
        if not isinstance(item, dict):
            raise ValueError('额外输入筛选条件不合法。')
        axis = str(item.get('axis') or '')
        operator = str(item.get('operator') or 'any')
        values = list(dict.fromkeys(str(label) for label in item.get('values') or [] if str(label)))
        if axis not in EXTRA_INPUT_AXES or operator not in {'any', 'all', 'none'}:
            raise ValueError('额外输入筛选条件不合法。')
        allowed = set(EXTRA_INPUT_AXES[axis]['values'].values())
        if not values or any(label not in allowed for label in values):
            raise ValueError('额外输入筛选标签不合法。')
        conditions.append({'axis': axis, 'operator': operator, 'values': values})
    return {'version': 1, 'run': run, 'relation': relation, 'conditions': conditions}


def extra_input_matches(summary: dict[str, Any], filter_value: dict[str, Any]) -> bool:
    checks = []
    for condition in filter_value.get('conditions', []):
        axis = (summary.get('axes') or {}).get(condition['axis']) or {}
        present = {label for label, count in (axis.get('counts') or {}).items() if int(count) > 0}
        selected = set(condition['values'])
        operator = condition['operator']
        checks.append(
            bool(present & selected) if operator == 'any'
            else selected <= present if operator == 'all'
            else axis.get('status') == 'available' and not bool(present & selected)
        )
    if not checks:
        return True
    return all(checks) if filter_value.get('relation') == 'all' else any(checks)


def public_input(value: Any) -> Any:
    value = redact_sensitive_fields(value)
    if isinstance(value, dict):
        return {k: ('[REDACTED PATH]' if re.search(r'path|location|directory', k, re.I)
                    else public_input(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [public_input(v) for v in value]
    if isinstance(value, str):
        if value.startswith(('/', 'file://')):
            return '[REDACTED PATH]'
        value = re.sub(r'(?:file://)?/(?:volume|nfs|home|Users|tmp|private|etc|root|mnt|srv|opt|var)/[^\s<>"\']+', '[REDACTED PATH]', value)
        value = re.sub(r'(?i)(bearer\s+)[\w.\-]+', r'\1[REDACTED]', value)
        value = re.sub(r'(?i)((?:api[_-]?key|password|secret|access_token)\s*[:=]\s*)[^\s,;]+', r'\1[REDACTED]', value)
        value = re.sub(r'sk-[A-Za-z0-9_-]{12,}', '[REDACTED]', value)
    return value


def case_input_projection(raw: dict, extra: dict, source_sha: str) -> dict:
    # Only explicit saved per-prediction fields. A Run template is never rendered here.
    raw = raw if isinstance(raw, dict) else {}
    containers = [(extra, 'model_extra'), (raw.get('model_extra', {}), 'raw.model_extra'), (raw, 'raw')]
    containers = [(v, p) for v, p in containers if isinstance(v, dict)]
    def saved(key):
        for container, prefix in containers:
            if key in container:
                return container[key], prefix + '.' + key
        return None, ''
    prompt, prompt_source = saved('prompt_text')
    if not isinstance(prompt, str):
        prompt, prompt_source = saved('actual_prompt')
    prompt = prompt if isinstance(prompt, str) else ''
    digest, _ = saved('prompt_sha256')
    stage, _ = saved('prompt_stage')
    config, config_source = saved('input_config')
    images, images_source = saved('image_inputs')
    media = []
    if isinstance(images, list):
        for index, entry in enumerate(images):
            entry = entry if isinstance(entry, dict) else {'image': entry}
            path = str(entry.get('image') or entry.get('path') or '')
            media.append({
                'order': index + 1,
                'reference_sha256': hashlib.sha256(path.encode()).hexdigest() if path else '',
                'content_sha256': entry.get('sha256') or entry.get('content_sha256') or '',
                **{k: entry[k] for k in ('type', 'timestamp', 'offset_sec', 'min_pixels', 'max_pixels') if k in entry},
            })
    generated, _ = saved('reason_generated')
    return public_input({
        'source_sha256': source_sha,
        'prompt': {'available': bool(prompt), 'source_type': 'actual_input' if prompt else 'not_saved',
                   'source': prompt_source if prompt else '', 'text': prompt,
                   'sha256': digest or '', 'hash_matches': (digest == hashlib.sha256(prompt.encode()).hexdigest()) if digest and prompt else None, 'computed_sha256': hashlib.sha256(prompt.encode()).hexdigest() if prompt else '',
                   'stage': stage or '', 'redacted': public_input(prompt) != prompt},
        'input': {'available': isinstance(config, dict), 'source_type': 'actual_input' if isinstance(config, dict) else 'not_saved',
                  'source': config_source, 'config': config if isinstance(config, dict) else {}},
        'media': {'available': isinstance(images, list), 'source': images_source,
                  'count': len(media) if isinstance(images, list) else None, 'items': media,
                  'asset_status': 'unverified_references' if media else 'not_saved',
                  'notice': '仅保存输入引用；未验证可访问资产与图片字节身份。看板媒体为参考媒体。'},
        'reason_status': 'not_generated' if generated is False else 'unknown',
        'extra_inputs': extra_input_summary(raw, extra),
    })
