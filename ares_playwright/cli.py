import argparse

from playwright.sync_api import sync_playwright

from .auth import print_validation_result, validate_saved_login_state
from .browser import launch_browser
from .config import (
    DEFAULT_CHROME_PATH,
    DEFAULT_REMOTE_STATE_PATH,
    DEFAULT_SSH_HOST,
    SCREENSHOT_DIR,
    STATE_FILE,
)
from .login import generate_login_state
from .models import AuthStatus, StateValidationResult
from .screenshot import take_screenshot
from .upload import upload_login_state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ares Studio 登录态验证、刷新、上传和截图工具"
    )
    parser.add_argument(
        "--mode",
        choices=["login", "auto", "shot", "validate-state", "upload-state"],
        default="auto",
    )
    parser.add_argument("--chrome-path", default=DEFAULT_CHROME_PATH)
    parser.add_argument("--ssh-host", default=DEFAULT_SSH_HOST)
    parser.add_argument("--remote-state-path", default=DEFAULT_REMOTE_STATE_PATH)
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="忽略现有登录态，强制重新登录",
    )
    parser.add_argument(
        "--skip-state-upload",
        action="store_true",
        help="只保存本地登录态，不上传远端",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="不等待人工处理验证码、MFA 或设备验证",
    )
    parser.add_argument(
        "--batch-mode", action="store_true", help="SCP 和 SSH 禁止密码交互"
    )
    parser.add_argument(
        "--keep-open", action="store_true", help="截图后保持浏览器打开"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无界面运行 Chrome，适用于没有 DISPLAY 的 SSH 会话",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="让 Chrome 绕过 HTTP(S) 代理，直接访问内网站点",
    )
    return parser.parse_args(argv)


def _generate(browser, args: argparse.Namespace) -> None:
    generate_login_state(
        browser=browser,
        state_file=STATE_FILE,
        ssh_host=args.ssh_host,
        remote_state_path=args.remote_state_path,
        skip_state_upload=args.skip_state_upload,
        batch_mode=args.batch_mode,
        non_interactive=args.non_interactive,
    )


def _validate(browser) -> StateValidationResult:
    result = validate_saved_login_state(browser, STATE_FILE)
    print_validation_result(result)
    return result


def _require_valid(browser) -> StateValidationResult:
    result = _validate(browser)
    if result.status != AuthStatus.VALID:
        raise RuntimeError(f"当前登录态不可用：{result.reason}")
    return result


def run_auto_mode(browser, args: argparse.Namespace) -> None:
    if args.force_login:
        print("[AUTO] 已启用 --force-login")
        _generate(browser, args)
    else:
        result = _validate(browser)
        if result.status == AuthStatus.VALID:
            print("[AUTO] 当前本地登录态有效")
            if not args.skip_state_upload:
                upload_login_state(
                    STATE_FILE,
                    args.ssh_host,
                    args.remote_state_path,
                    batch_mode=args.batch_mode,
                )
        else:
            print("[AUTO] 当前登录态不可用或无法确认，开始重新登录")
            _generate(browser, args)

    take_screenshot(browser, STATE_FILE, SCREENSHOT_DIR, args.keep_open)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    print(f"[CONFIG] mode              = {args.mode}")
    print(f"[CONFIG] chrome path       = {args.chrome_path}")
    print(f"[CONFIG] local state       = {STATE_FILE.resolve()}")
    print(f"[CONFIG] remote state      = {args.ssh_host}:{args.remote_state_path}")
    print(f"[CONFIG] skip state upload = {args.skip_state_upload}")
    print(f"[CONFIG] non-interactive   = {args.non_interactive}")
    print(f"[CONFIG] headless          = {args.headless}")
    print(f"[CONFIG] no proxy          = {args.no_proxy}")

    with sync_playwright() as playwright:
        browser = launch_browser(
            playwright,
            args.chrome_path,
            headless=args.headless,
            no_proxy=args.no_proxy,
        )
        try:
            if args.mode == "login":
                _generate(browser, args)
            elif args.mode == "auto":
                run_auto_mode(browser, args)
            elif args.mode == "shot":
                _require_valid(browser)
                take_screenshot(
                    browser, STATE_FILE, SCREENSHOT_DIR, args.keep_open
                )
            elif args.mode == "validate-state":
                if _validate(browser).status != AuthStatus.VALID:
                    raise SystemExit(1)
            elif args.mode == "upload-state":
                _require_valid(browser)
                upload_login_state(
                    STATE_FILE,
                    args.ssh_host,
                    args.remote_state_path,
                    batch_mode=args.batch_mode,
                )
        finally:
            browser.close()
