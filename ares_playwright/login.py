import getpass
import os
import re
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .auth import print_validation_result, validate_saved_login_state
from .config import ARES_URL, NAVIGATION_TIMEOUT_MS, TARGET_HOST
from .models import AuthStatus
from .upload import upload_login_state


USERNAME_SELECTOR = (
    'input[placeholder*="账户"]:visible, '
    'input[placeholder*="账号"]:visible, '
    'input[placeholder*="用户名"]:visible, '
    'input[autocomplete="username"]:visible, '
    'input[name="username"]:visible, '
    'input[name="account"]:visible, '
    'input[type="email"]:visible, '
    'input[type="text"]:visible'
)

LOGIN_BUTTON_SELECTOR = (
    'button:has-text("登录"):visible, '
    'input[type="submit"][value*="登录"]:visible, '
    '[role="button"]:has-text("登录"):visible, '
    'a:has-text("登录"):visible'
)


def get_login_credentials(non_interactive: bool = False) -> tuple[str, str]:
    username = os.getenv("ARES_USERNAME", "").strip()
    password = os.getenv("ARES_PASSWORD", "")

    if non_interactive and (not username or not password):
        raise RuntimeError(
            "--non-interactive 模式要求设置 ARES_USERNAME 和 ARES_PASSWORD"
        )
    if not username:
        username = input("请输入登录账号：").strip()
    if not password:
        password = getpass.getpass("请输入登录密码：")
    if not username:
        raise ValueError("登录账号不能为空")
    if not password:
        raise ValueError("登录密码不能为空")
    return username, password


def _find_login_frame(
    page,
    timeout_ms: int = 60_000,
    target_stable_ms: int = 8_000,
):
    deadline = time.monotonic() + timeout_ms / 1000
    target_since = None
    while time.monotonic() < deadline:
        for frame in page.frames:
            try:
                if frame.locator('input[type="password"]:visible').count() > 0:
                    return frame
            except Exception:
                continue

        if TARGET_HOST in page.url.lower():
            if target_since is None:
                target_since = time.monotonic()
            elif (time.monotonic() - target_since) * 1000 >= target_stable_ms:
                return None
        else:
            target_since = None
        page.wait_for_timeout(500)
    raise RuntimeError("等待登录表单超时")


def auto_login(page, non_interactive: bool = False) -> None:
    """Fill credentials; security challenges remain a manual user action."""
    frame = _find_login_frame(page)
    if frame is None:
        print("[LOGIN] 页面已进入 Voyager，无需填写账号密码")
        return

    username, password = get_login_credentials(non_interactive)
    try:
        username_input = frame.locator(USERNAME_SELECTOR).first
        password_input = frame.locator('input[type="password"]:visible').first
        login_button = frame.locator(LOGIN_BUTTON_SELECTOR).first

        # Prefer the semantic role when available, then fall back to the SSO
        # page's submit controls or an exact visible text match.
        role_button = frame.get_by_role(
            "button", name=re.compile(r"登\s*录")
        ).first
        if role_button.count() > 0:
            login_button = role_button
        elif login_button.count() == 0:
            login_button = frame.get_by_text("登录", exact=True).first

        username_input.wait_for(state="visible", timeout=60_000)
        password_input.wait_for(state="visible", timeout=60_000)
        login_button.wait_for(state="visible", timeout=60_000)
        username_input.fill(username)
        password_input.fill(password)
        if username_input.input_value() != username:
            raise RuntimeError("SSO 账号输入失败")
        if not password_input.input_value():
            raise RuntimeError("SSO 密码输入失败")
        login_button.click()

        try:
            page.wait_for_url(
                f"**://{TARGET_HOST}/**", timeout=NAVIGATION_TIMEOUT_MS
            )
        except PlaywrightTimeoutError as exc:
            if non_interactive:
                raise RuntimeError(
                    "登录后未进入 Voyager，可能存在验证码、MFA 或设备验证"
                ) from exc
            print("[WARN] 可能存在验证码、MFA 或设备验证")
            input("请在浏览器中完成剩余认证后按 Enter...")
    finally:
        password = ""


def save_storage_state(context, state_file: Path) -> None:
    print(f"[LOGIN] 保存本地登录态：{state_file.resolve()}")
    state_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        context.storage_state(path=str(state_file), indexed_db=True)
    except TypeError:
        context.storage_state(path=str(state_file))

    if not state_file.is_file() or state_file.stat().st_size == 0:
        raise RuntimeError("登录态文件保存失败")
    try:
        state_file.chmod(0o600)
    except OSError as exc:
        print(f"[WARN] 无法设置本地登录态权限为 600：{exc}")


def generate_login_state(
    browser,
    state_file: Path,
    ssh_host: str,
    remote_state_path: str,
    skip_state_upload: bool,
    batch_mode: bool,
    non_interactive: bool,
) -> None:
    """Log in, save state, validate it in a fresh context, then upload."""
    print("[LOGIN] 开始生成 Ares Studio 登录态")
    context = browser.new_context(ignore_https_errors=True, no_viewport=True)
    page = context.new_page()
    try:
        page.goto(
            ARES_URL,
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )
        auto_login(page, non_interactive=non_interactive)
        save_storage_state(context, state_file)
    finally:
        context.close()

    # This must happen after closing the login context: validation may only rely
    # on the serialized state, never on live cookies from the login context.
    result = validate_saved_login_state(browser, state_file)
    print_validation_result(result)
    if result.status != AuthStatus.VALID:
        raise RuntimeError(f"新生成的登录态验证失败：{result.reason}")

    if skip_state_upload:
        print("[UPLOAD] 已通过 --skip-state-upload 跳过登录态上传")
        return
    upload_login_state(
        state_file,
        ssh_host,
        remote_state_path,
        batch_mode=batch_mode,
    )
