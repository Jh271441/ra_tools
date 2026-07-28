#!/usr/bin/env python3
"""跨机调用 lingma-proxy / 其它 OpenAI 兼容多模态接口。

图片在客户端本机读入后编成 data URL 发出（推荐跨机）；也可传 http(s)
图链，由 proxy 主机拉取。不要把别的机器上的本地路径塞给 proxy。

鉴权：--api-key > 环境变量 LINGMA_API_KEY / OPENAI_API_KEY。
默认 profile=qoder（nginx /qoder/v1 → 8096 IPC）。

示例：
  export LINGMA_API_KEY='你的网关 Bearer token'

  # 默认 qoder
  python3 multimodal_api_client.py -p "只回 pong"
  python3 multimodal_api_client.py -i ./shot.png -p "描述这张图"

  # Lingma remote 网关
  python3 multimodal_api_client.py --profile lingma -i ./a.png -p "描述图片"

  # 公网/内网图链（proxy 侧 GET）
  python3 multimodal_api_client.py --image-url https://example.com/a.jpg -p "描述"

  # 完全自定义
  python3 multimodal_api_client.py \\
    --base-url http://172.29.58.39/qoder/v1 \\
    --api-key "$LINGMA_API_KEY" \\
    --model auto \\
    -i ~/Pictures/a.png \\
    -p "描述图片"

  # 兼容旧用法（完整 chat/completions URL）
  python3 multimodal_api_client.py \\
    --url http://172.29.58.39/qoder/v1/chat/completions \\
    --api-key "$LINGMA_API_KEY" \\
    --model auto \\
    --prompt "hello"
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    print("error: need requests (`pip install requests`)", file=sys.stderr)
    raise SystemExit(2)

# ---------------------------------------------------------------------------
# 预设：别的机器走 nginx 网关，不要写 127.0.0.1
# api_key 不写死，运行时从 env / CLI 注入
# ---------------------------------------------------------------------------
PROFILES: Dict[str, Dict[str, str]] = {
    # Qoder IPC @8096，经 nginx /qoder/v1/（proxy 机上 Qoder 桌面需开着）
    "qoder": {
        "base_url": "http://172.29.58.39/qoder/v1",
        "model": "auto",
    },
    # Lingma remote @8095，经 nginx /v1/
    "lingma": {
        "base_url": "http://172.29.58.39/v1",
        "model": "kmodel",
    },
    # 仅在 proxy 本机调试
    "local-qoder": {
        "base_url": "http://127.0.0.1:8096/v1",
        "model": "auto",
    },
    "local-lingma": {
        "base_url": "http://127.0.0.1:8095/v1",
        "model": "kmodel",
    },
}

DEFAULT_PROFILE = "qoder"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_SIDE = 1568


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def resolve_api_key(cli_value: Optional[str]) -> str:
    """CLI > LINGMA_API_KEY > OPENAI_API_KEY > 空。"""
    if cli_value is not None:
        return cli_value
    return (
        os.environ.get("LINGMA_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("image/"):
        return mime
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")


def shrink_image_bytes(data: bytes, mime: str) -> tuple[bytes, str]:
    """可选：有 Pillow 时把过大图片压到 proxy 友好尺寸。"""
    if len(data) <= MAX_IMAGE_BYTES:
        return data, mime
    try:
        from io import BytesIO

        from PIL import Image  # type: ignore
    except ImportError:
        print(
            f"warn: image is {len(data)} bytes (> {MAX_IMAGE_BYTES}); "
            "install Pillow to auto-shrink, or pass a smaller file",
            file=sys.stderr,
        )
        return data, mime

    im = Image.open(BytesIO(data)).convert("RGB")
    im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=85)
    out = buf.getvalue()
    print(
        f"info: shrunk image {len(data)} -> {len(out)} bytes "
        f"({im.size[0]}x{im.size[1]} jpeg)",
        file=sys.stderr,
    )
    return out, "image/jpeg"


def encode_image(image_path: str) -> str:
    """兼容旧接口：读本地图 → base64 字符串（不带 data: 前缀）。"""
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def file_to_data_url(path: Path) -> str:
    """本机读图 → data URL。跨机唯一推荐的本地图方式。"""
    if not path.is_file():
        die(f"image not found: {path}")
    raw = path.read_bytes()
    if not raw:
        die(f"empty image: {path}")
    mime = guess_mime(path)
    raw, mime = shrink_image_bytes(raw, mime)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_user_content(
    text_prompt: str,
    *,
    image_path: Optional[str] = None,
    image_url: Optional[str] = None,
) -> Any:
    """组装 OpenAI multimodal content。无图时仍用 list，兼容旧脚本。"""
    prompt = (text_prompt or "").strip() or "请描述这张图片。"
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

    if image_path and image_url:
        die("use either --image or --image-url, not both")

    if image_path:
        path = Path(image_path).expanduser().resolve()
        data_url = file_to_data_url(path)
        print(
            f"info: loaded local image {path} as data URL "
            f"({len(data_url)} chars)",
            file=sys.stderr,
        )
        content.append(
            {"type": "image_url", "image_url": {"url": data_url}}
        )
    elif image_url:
        ref = image_url.strip()
        if ref.startswith("file:") or (
            ref.startswith("/") and not ref.startswith("//")
        ):
            print(
                "warn: file path / file:// in --image-url is resolved on the "
                "PROXY host, not this machine. Prefer --image for local files.",
                file=sys.stderr,
            )
        content.append({"type": "image_url", "image_url": {"url": ref}})

    return content


def create_payload(
    model: str,
    text_prompt: str,
    image_path: Optional[str] = None,
    image_url: Optional[str] = None,
    stream: bool = False,
) -> Dict[str, Any]:
    """Create a payload for multimodal requests."""
    return {
        "model": model,
        "stream": stream,
        "messages": [
            {
                "role": "user",
                "content": build_user_content(
                    text_prompt,
                    image_path=image_path,
                    image_url=image_url,
                ),
            }
        ],
    }


def send_multimodal_request(
    url: str,
    api_key: str,
    model: str,
    text_prompt: str,
    image_path: Optional[str] = None,
    image_url: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    stream: bool = False,
    timeout: float = 180.0,
    no_proxy: bool = False,
) -> Dict[str, Any]:
    """POST OpenAI chat.completions。stream=True 时边打边收，返回空 dict。"""
    # 允许传 base (/v1) 或完整 /chat/completions
    endpoint = url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = endpoint + "/chat/completions"

    payload = create_payload(
        model,
        text_prompt,
        image_path=image_path,
        image_url=image_url,
        stream=stream,
    )

    request_headers = {"Content-Type": "application/json"}
    if api_key:
        request_headers["Authorization"] = f"Bearer {api_key}"
    if stream:
        request_headers["Accept"] = "text/event-stream"
    if headers:
        request_headers.update(headers)

    # no_proxy=True: 本请求不走 HTTP(S)_PROXY / 系统代理，不改进程环境变量
    request_kwargs: Dict[str, Any] = {
        "headers": request_headers,
        "json": payload,
        "stream": stream,
        "timeout": timeout,
    }
    if no_proxy:
        request_kwargs["proxies"] = {"http": None, "https": None}

    t0 = time.time()
    try:
        response = requests.post(endpoint, **request_kwargs)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error making request: {e}", file=sys.stderr)
        if getattr(e, "response", None) is not None:
            print(f"Response content: {e.response.text}", file=sys.stderr)
        raise

    if stream:
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload_text = line[5:].strip()
            if not payload_text or payload_text == "[DONE]":
                if payload_text == "[DONE]":
                    print()
                continue
            try:
                chunk = json.loads(payload_text)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                print(piece, end="", flush=True)
        print(
            f"\n--- stream done in {time.time() - t0:.1f}s ---",
            file=sys.stderr,
        )
        return {}

    result = response.json()
    result["_elapsed_s"] = round(time.time() - t0, 2)
    result["_http_status"] = response.status_code
    return result


def print_result(result: Dict[str, Any], *, raw_json: bool, output: Optional[str]) -> None:
    if not result:
        return

    if raw_json or output:
        out = {k: v for k, v in result.items() if not str(k).startswith("_")}
        text = json.dumps(out, indent=2, ensure_ascii=False)
        if output:
            Path(output).write_text(text, encoding="utf-8")
            print(f"Response saved to {output}", file=sys.stderr)
        else:
            print(text)
        return

    choices = result.get("choices") or []
    content = ""
    if choices:
        content = (choices[0].get("message") or {}).get("content") or ""
    print(content)
    print(
        f"--- model={result.get('model')} "
        f"status={result.get('_http_status')} "
        f"elapsed={result.get('_elapsed_s')}s "
        f"usage={result.get('usage')} ---",
        file=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="跨机调用 lingma-proxy 文本/看图（OpenAI chat.completions）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default=DEFAULT_PROFILE,
        help=f"预设 base-url/model（默认 {DEFAULT_PROFILE}）",
    )
    p.add_argument(
        "--base-url",
        help="覆盖 profile 的 API 根，如 http://host/qoder/v1",
    )
    p.add_argument(
        "--url",
        help="兼容旧参数：完整 chat/completions URL，或 /v1 根；"
        "设置后忽略 profile/base-url",
    )
    p.add_argument(
        "--api-key",
        help="Bearer token；默认读 LINGMA_API_KEY 或 OPENAI_API_KEY；"
        "传空字符串可显式关掉鉴权",
    )
    p.add_argument("--model", help="覆盖 profile 的模型名")
    p.add_argument(
        "--prompt",
        "-p",
        default="请用中文简要描述这张图片的内容。",
        help="用户文本",
    )
    p.add_argument(
        "--image",
        "-i",
        help="本机图片路径：读入并编码为 data URL（跨机推荐）",
    )
    p.add_argument(
        "--image-url",
        help="直接作为 image_url 发送：http(s) 由 proxy 拉取；"
        "也可手动塞 data:…；不要填别的机器的本地路径",
    )
    p.add_argument("--stream", action="store_true", help="SSE 流式输出")
    p.add_argument("--timeout", type=float, default=180.0, help="HTTP 超时秒数")
    p.add_argument(
        "--no-proxy",
        action="store_true",
        help="仅本请求绕过 HTTP(S)_PROXY/系统代理（不改环境变量；"
        "适合 Clash 劫持 *.ts.net / 100.x 的机器）",
    )
    p.add_argument("--raw-json", action="store_true", help="打印完整 JSON 响应")
    p.add_argument("--output", "-o", help="把完整 JSON 响应写到文件")
    p.add_argument(
        "--custom-header",
        action="append",
        help="自定义头 'Key:Value'（可重复）",
    )
    p.add_argument(
        "--list-profiles",
        action="store_true",
        help="列出内置 profile 后退出",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_profiles:
        for name, cfg in sorted(PROFILES.items()):
            print(f"{name:14} base={cfg['base_url']}  model={cfg['model']}")
        print(
            "api key: set LINGMA_API_KEY / OPENAI_API_KEY or pass --api-key",
            file=sys.stderr,
        )
        return 0

    profile = PROFILES[args.profile]
    if args.url:
        endpoint = args.url
        model = args.model or profile["model"]
    else:
        endpoint = (args.base_url or profile["base_url"]).rstrip("/")
        model = args.model or profile["model"]

    api_key = resolve_api_key(args.api_key)

    if not api_key and "127.0.0.1" not in endpoint and "localhost" not in endpoint:
        print(
            "warn: no API key; nginx will likely return 401. "
            "export LINGMA_API_KEY=... or pass --api-key",
            file=sys.stderr,
        )

    headers: Dict[str, str] = {}
    if args.custom_header:
        for header_str in args.custom_header:
            parts = header_str.split(":", 1)
            if len(parts) == 2:
                headers[parts[0].strip()] = parts[1].strip()
            else:
                print(
                    f"warn: invalid --custom-header {header_str!r}, "
                    "expected 'Key:Value'",
                    file=sys.stderr,
                )

    print(
        f"info: POST {endpoint}  model={model}  "
        f"auth={'Bearer' if api_key else 'none'}  "
        f"image={'yes' if (args.image or args.image_url) else 'no'}  "
        f"proxy={'off' if args.no_proxy else 'env'}",
        file=sys.stderr,
    )

    try:
        result = send_multimodal_request(
            url=endpoint,
            api_key=api_key,
            model=model,
            text_prompt=args.prompt,
            image_path=args.image,
            image_url=args.image_url,
            headers=headers or None,
            stream=args.stream,
            timeout=args.timeout,
            no_proxy=args.no_proxy,
        )
    except Exception as e:
        print(f"Failed to send request: {e}", file=sys.stderr)
        return 1

    print_result(result, raw_json=args.raw_json, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
