import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .config import (
    AUTH_CHECK_URL,
    LOGIN_HOST,
    NAVIGATION_TIMEOUT_MS,
    TARGET_HOST,
)
from .models import AuthStatus, StateValidationResult


APP_ERROR_TEXT = "Service not registered, please register service first"


def validate_state_file_structure(state_file: Path) -> StateValidationResult:
    """Reject missing, unreadable, or malformed Playwright storage state."""
    if not state_file.exists():
        return StateValidationResult(AuthStatus.INVALID, "登录态文件不存在")

    try:
        if state_file.stat().st_size == 0:
            return StateValidationResult(AuthStatus.INVALID, "登录态文件为空")
        with state_file.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        return StateValidationResult(
            AuthStatus.INVALID, f"登录态 JSON 解析失败：{exc}"
        )
    except OSError as exc:
        return StateValidationResult(
            AuthStatus.UNKNOWN, f"无法读取登录态文件：{exc}"
        )

    if not isinstance(data, dict):
        return StateValidationResult(
            AuthStatus.INVALID, "登录态根节点不是 JSON 对象"
        )

    cookies = data.get("cookies")
    origins = data.get("origins")
    if not isinstance(cookies, list):
        return StateValidationResult(
            AuthStatus.INVALID, "登录态中的 cookies 字段不是列表"
        )
    if not isinstance(origins, list):
        return StateValidationResult(
            AuthStatus.INVALID, "登录态中的 origins 字段不是列表"
        )
    if not cookies and not origins:
        return StateValidationResult(
            AuthStatus.INVALID, "登录态中 cookies 和 origins 均为空"
        )

    return StateValidationResult(AuthStatus.VALID, "登录态 JSON 结构正常")


def page_has_login_form(page) -> bool:
    """Look for a visible SSO login form in the page or any child frame."""
    for frame in page.frames:
        try:
            password = frame.locator('input[type="password"]:visible')
            if password.count() > 0:
                return True

            username = frame.locator(
                'input[name="username"]:visible, '
                'input[placeholder*="账户"]:visible, '
                'input[placeholder*="账号"]:visible, '
                'input[placeholder*="用户名"]:visible'
            )
            login_button = frame.get_by_role("button", name="登录", exact=False)
            if username.count() > 0 and login_button.count() > 0:
                return True
        except Exception:
            continue
    return False


def _read_body(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5_000)
    except PlaywrightTimeoutError:
        return ""


def validate_saved_login_state(
    browser, state_file: Path
) -> StateValidationResult:
    """Validate storage state in a brand-new BrowserContext and real page load."""
    structure_result = validate_state_file_structure(state_file)
    if structure_result.status != AuthStatus.VALID:
        return structure_result

    try:
        context = browser.new_context(
            storage_state=str(state_file),
            ignore_https_errors=True,
            no_viewport=True,
        )
    except Exception as exc:
        return StateValidationResult(
            AuthStatus.INVALID, f"Playwright 无法加载登录态：{exc}"
        )

    page = None
    try:
        page = context.new_page()
        page.goto(
            AUTH_CHECK_URL,
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )
        page.wait_for_timeout(3_000)

        final_url = page.url
        final_url_lower = final_url.lower()
        title_lower = page.title().lower()

        if LOGIN_HOST in final_url_lower:
            return StateValidationResult(
                AuthStatus.INVALID,
                "访问目标页面后被重定向到登录页",
                final_url,
            )
        if page_has_login_form(page):
            return StateValidationResult(
                AuthStatus.INVALID, "页面中检测到登录表单", final_url
            )
        if "统一登录" in title_lower or "sso login" in title_lower:
            return StateValidationResult(
                AuthStatus.INVALID, "页面标题表明当前处于登录页", final_url
            )
        if TARGET_HOST in final_url_lower:
            body_text = _read_body(page).lower()
            app_error = ""
            if (
                "service not registered" in body_text
                or "please register service first" in body_text
            ):
                app_error = APP_ERROR_TEXT
            return StateValidationResult(
                AuthStatus.VALID,
                "登录态有效，已进入 Voyager",
                final_url,
                app_error,
            )

        return StateValidationResult(
            AuthStatus.UNKNOWN,
            "最终进入了未知页面，无法确认登录状态",
            final_url,
        )
    except PlaywrightTimeoutError:
        return StateValidationResult(
            AuthStatus.UNKNOWN,
            "验证登录态时页面加载超时",
            page.url if page else "",
        )
    except Exception as exc:
        return StateValidationResult(
            AuthStatus.UNKNOWN,
            f"验证登录态时发生异常：{exc}",
            page.url if page else "",
        )
    finally:
        context.close()


def print_validation_result(result: StateValidationResult) -> None:
    print(f"[STATE] 状态：{result.status.value}")
    print(f"[STATE] 原因：{result.reason}")
    print(f"[STATE] URL：{result.final_url}")
    if result.app_error:
        print(f"[STATE] 应用错误：{result.app_error}")
