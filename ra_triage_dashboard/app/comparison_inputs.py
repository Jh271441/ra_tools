"""Read-only provenance projection; never resolve inference paths as web assets."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .sanitization import redact_sensitive_fields


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
    })
