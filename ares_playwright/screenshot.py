from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .config import ARES_URL, NAVIGATION_TIMEOUT_MS


def check_page_error(page) -> bool:
    try:
        body_text = page.locator("body").inner_text(timeout=10_000).strip()
    except PlaywrightTimeoutError:
        return False

    lowered = body_text.lower()
    if (
        "service not registered" not in lowered
        and "please register service first" not in lowered
    ):
        return False

    print("[WARN] Voyager 服务未注册；认证仍有效，将保存错误页面截图")
    return True


def wait_for_ares_loaded(page) -> None:
    print("[1/5] 等待 document.readyState=complete ...")
    page.wait_for_function(
        "() => document.readyState === 'complete'",
        timeout=NAVIGATION_TIMEOUT_MS,
    )

    print("[2/5] 等待页面中出现有效 Canvas ...")
    try:
        page.wait_for_function(
            """
            () => Array.from(document.querySelectorAll("canvas")).some(canvas => {
                const rect = canvas.getBoundingClientRect();
                return canvas.width > 100 && canvas.height > 100 &&
                    rect.width > 100 && rect.height > 100;
            })
            """,
            timeout=NAVIGATION_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        print("[WARN] 没有等到明显的 Canvas，继续执行")

    print("[3/5] 触发 resize，让 Ares 重新计算布局 ...")
    page.evaluate(
        """
        () => {
            window.dispatchEvent(new Event("resize"));
            setTimeout(() => window.dispatchEvent(new Event("resize")), 500);
            setTimeout(() => window.dispatchEvent(new Event("resize")), 1500);
        }
        """
    )

    print("[4/5] 等待 Canvas 和页面尺寸稳定 ...")
    try:
        page.wait_for_function(
            """
            async () => {
                const snapshot = () => JSON.stringify({
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    bodyWidth: document.body.clientWidth,
                    bodyHeight: document.body.clientHeight,
                    rects: Array.from(document.querySelectorAll("canvas")).map(c => {
                        const r = c.getBoundingClientRect();
                        return [Math.round(r.x), Math.round(r.y), Math.round(r.width),
                            Math.round(r.height), c.width, c.height];
                    }),
                });
                const first = snapshot();
                await new Promise(resolve => setTimeout(resolve, 1200));
                const second = snapshot();
                await new Promise(resolve => setTimeout(resolve, 1200));
                return first === second && second === snapshot();
            }
            """,
            timeout=60_000,
        )
    except PlaywrightTimeoutError:
        print("[WARN] 页面尺寸没有完全稳定，继续截图")

    print("[5/5] 额外等待 3 秒，让地图和轨迹完成渲染 ...")
    page.wait_for_timeout(3_000)


def print_page_info(page) -> None:
    info = page.evaluate(
        """
        () => ({
            url: location.href,
            title: document.title,
            readyState: document.readyState,
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            devicePixelRatio: window.devicePixelRatio,
            canvasCount: document.querySelectorAll("canvas").length,
        })
        """
    )
    print(f"[INFO] 页面信息：{info}")


def take_screenshot(
    browser, state_file: Path, output_dir: Path, keep_open: bool
) -> Path:
    """Take a local screenshot with state already validated by the caller."""
    if not state_file.is_file():
        raise FileNotFoundError(f"没有找到本地登录态：{state_file.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = output_dir / f"ares_{timestamp}.png"
    context = browser.new_context(
        storage_state=str(state_file),
        ignore_https_errors=True,
        no_viewport=True,
    )
    page = context.new_page()
    try:
        page.goto(
            ARES_URL,
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )
        page.wait_for_timeout(1_500)
        if not check_page_error(page):
            wait_for_ares_loaded(page)
        print_page_info(page)
        page.screenshot(path=str(screenshot_path), full_page=False)
        if not screenshot_path.is_file():
            raise RuntimeError("截图文件生成失败")
        print(f"[SHOT] 截图完成：{screenshot_path.resolve()}")
        print("[SHOT] 截图不会上传到远端")
        if keep_open:
            input("按 Enter 关闭浏览器...")
        return screenshot_path
    finally:
        context.close()
