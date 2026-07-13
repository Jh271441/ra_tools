from pathlib import Path
from datetime import datetime
import argparse
import shlex
import shutil
import subprocess

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


URL = (
    "https://voyager.intra.xiaojukeji.com/static/ares-studio/"
    "?ds=voy-ws-car"
    "&ds.start=1783332960157"
    "&ds.end=1783333000157"
    "&ds.trip_id=10315_20260706_180656"
    "&ds.server="
    "&layoutId=9e3be845-41e7-485d-90d3-d46a46a5ab19"
    "&time=2026-07-06T10%3A16%3A20.256999998Z"
)

# 本地 Google Chrome 路径
DEFAULT_CHROME_PATH = "/usr/bin/google-chrome"

# 本地登录态文件
STATE_FILE = Path("ares_storage_state.json")

# 本地截图目录
OUT_DIR = Path("playwright_screenshots")

# SCP 默认配置
DEFAULT_SSH_HOST = "cloud_server"
DEFAULT_REMOTE_STATE_PATH = "/tmp/ares_storage_state.json"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Ares Studio 登录态生成、上传和截图工具"
    )

    parser.add_argument(
        "--mode",
        choices=["login", "shot", "auto", "upload-state"],
        default="auto",
        help=(
            "login：生成登录态并上传；"
            "shot：使用本地登录态截图；"
            "auto：没有登录态时先登录上传，然后截图；"
            "upload-state：仅上传已有登录态"
        ),
    )

    parser.add_argument(
        "--chrome-path",
        default=DEFAULT_CHROME_PATH,
        help=f"Chrome 可执行文件路径，默认：{DEFAULT_CHROME_PATH}",
    )

    parser.add_argument(
        "--ssh-host",
        default=DEFAULT_SSH_HOST,
        help=f"SSH 主机或 ~/.ssh/config 别名，默认：{DEFAULT_SSH_HOST}",
    )

    parser.add_argument(
        "--remote-state-path",
        default=DEFAULT_REMOTE_STATE_PATH,
        help=(
            "登录态在远端的完整路径，"
            f"默认：{DEFAULT_REMOTE_STATE_PATH}"
        ),
    )

    parser.add_argument(
        "--skip-state-upload",
        action="store_true",
        help="生成登录态后只保存在本地，不上传",
    )

    parser.add_argument(
        "--batch-mode",
        action="store_true",
        help="启用 SSH BatchMode，禁止交互式输入密码",
    )

    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="截图后保持浏览器打开，按 Enter 后关闭",
    )

    return parser.parse_args()


def launch_browser(playwright, chrome_path: str):
    """启动系统中的 Google Chrome。"""

    chrome = Path(chrome_path)

    if not chrome.exists():
        raise FileNotFoundError(
            f"没有找到 Chrome：{chrome_path}\n"
            "可以执行以下命令确认路径：\n"
            "  which google-chrome\n"
            "  which google-chrome-stable\n"
            "然后通过 --chrome-path 指定。"
        )

    return playwright.chromium.launch(
        executable_path=chrome_path,
        headless=False,
        args=[
            "--start-maximized",
            "--window-size=2560,1440",
        ],
    )


def upload_login_state(
    state_file: Path,
    ssh_host: str,
    remote_state_path: str,
    batch_mode: bool = False,
) -> str:
    """
    使用 SCP 将本地登录态上传到远端。

    例如：
        ares_storage_state.json
            ->
        cloud_server:/tmp/ares_storage_state.json
    """

    state_file = state_file.resolve()

    if not state_file.exists():
        raise FileNotFoundError(
            f"登录态文件不存在：{state_file}"
        )

    if shutil.which("scp") is None:
        raise RuntimeError(
            "没有找到 scp 命令，请安装 OpenSSH Client。"
        )

    if shutil.which("ssh") is None:
        raise RuntimeError(
            "没有找到 ssh 命令，请安装 OpenSSH Client。"
        )

    if not remote_state_path.startswith("/"):
        raise ValueError(
            "远端登录态路径必须是绝对路径，例如："
            "/tmp/ares_storage_state.json"
        )

    # 登录态包含 Cookie 等敏感认证信息。
    try:
        state_file.chmod(0o600)
    except OSError as exc:
        print(f"[WARN] 无法设置本地文件权限为 600：{exc}")

    remote_target = f"{ssh_host}:{remote_state_path}"

    scp_command = [
        "scp",
        "-p",  # 尽量保留本地的 600 权限
        "-o",
        "ConnectTimeout=15",
    ]

    if batch_mode:
        scp_command.extend([
            "-o",
            "BatchMode=yes",
        ])

    scp_command.extend([
        str(state_file),
        remote_target,
    ])

    print()
    print("[UPLOAD] 开始上传登录态")
    print(f"[UPLOAD] 本地：{state_file}")
    print(f"[UPLOAD] 远端：{remote_target}")

    try:
        subprocess.run(
            scp_command,
            check=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "SCP 上传超过 300 秒，已终止。"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"SCP 上传登录态失败，退出码：{exc.returncode}"
        ) from exc

    # 再通过 SSH 明确把远端权限设置为 600。
    remote_chmod_command = (
        f"chmod 600 -- {shlex.quote(remote_state_path)}"
    )

    ssh_command = [
        "ssh",
        "-o",
        "ConnectTimeout=15",
    ]

    if batch_mode:
        ssh_command.extend([
            "-o",
            "BatchMode=yes",
        ])

    ssh_command.extend([
        ssh_host,
        remote_chmod_command,
    ])

    try:
        subprocess.run(
            ssh_command,
            check=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "登录态已上传，但设置远端文件权限时超时。"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "登录态已上传，但无法将远端文件权限设置为 600。"
        ) from exc

    print(f"[UPLOAD] 登录态上传完成：{remote_target}")
    print("[UPLOAD] 远端文件权限已设置为 600")

    return remote_target


def save_storage_state(context):
    """
    保存 Playwright 登录态。

    新版 Playwright 支持 indexed_db=True；
    如果当前版本不支持，则自动退回普通 storage_state。
    """

    print(f"[LOGIN] 保存本地登录态：{STATE_FILE.resolve()}")

    try:
        context.storage_state(
            path=str(STATE_FILE),
            indexed_db=True,
        )
    except TypeError:
        # 兼容较旧版本 Playwright。
        context.storage_state(
            path=str(STATE_FILE),
        )

    if not STATE_FILE.exists():
        raise RuntimeError("登录态文件保存失败。")

    try:
        STATE_FILE.chmod(0o600)
    except OSError as exc:
        print(f"[WARN] 无法设置本地登录态权限为 600：{exc}")


def generate_login_state(
    browser,
    ssh_host: str,
    remote_state_path: str,
    skip_state_upload: bool,
    batch_mode: bool,
):
    """
    手动登录，保存本地登录态，然后上传登录态文件。
    """

    print("=" * 70)
    print("[LOGIN] 开始生成 Ares Studio 登录态")
    print(f"[LOGIN] 本地文件：{STATE_FILE.resolve()}")
    print(f"[LOGIN] 远端文件：{ssh_host}:{remote_state_path}")
    print("=" * 70)

    context = browser.new_context(
        ignore_https_errors=True,
        no_viewport=True,
    )

    page = context.new_page()

    try:
        print("[OPEN] 打开 Ares Studio ...")

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=120_000,
        )

        print()
        print("请在浏览器中完成以下操作：")
        print("1. 完成公司账号登录")
        print("2. 确认已经进入 Ares Studio")
        print("3. 确认当前页面能够正常访问")
        print("4. 回到终端按 Enter")
        print()

        input("登录完成后按 Enter 保存登录态...")

        save_storage_state(context)

        print(f"[LOGIN] 本地登录态已保存：{STATE_FILE.resolve()}")

        if skip_state_upload:
            print(
                "[UPLOAD] 已通过 --skip-state-upload "
                "跳过登录态上传。"
            )
        else:
            remote_target = upload_login_state(
                state_file=STATE_FILE,
                ssh_host=ssh_host,
                remote_state_path=remote_state_path,
                batch_mode=batch_mode,
            )

            print()
            print("=" * 70)
            print("[LOGIN] 登录态生成和上传完成")
            print(f"[LOCAL]  {STATE_FILE.resolve()}")
            print(f"[REMOTE] {remote_target}")
            print("=" * 70)

    finally:
        context.close()


def check_page_error(page) -> bool:
    """
    检查页面是否出现明确的服务错误。
    """

    try:
        body_text = page.locator("body").inner_text(
            timeout=10_000
        )
    except PlaywrightTimeoutError:
        return False

    body_text = body_text.strip()

    error_messages = [
        "Service not registered",
        "please register service first",
    ]

    if any(
        message.lower() in body_text.lower()
        for message in error_messages
    ):
        print()
        print("=" * 70)
        print("[ERROR PAGE] 页面返回：")
        print(body_text[:2000])
        print("=" * 70)
        print(
            "[WARN] 这通常表示对应服务尚未注册，"
            "不是 Playwright 截图代码本身的问题。"
        )
        print("[WARN] 将直接保存错误页面截图。")
        print()

        return True

    return False


def wait_for_ares_loaded(page):
    """
    等待 Ares Studio 的 SPA、Canvas 和 WebGL 内容完成主要渲染。
    """

    print("[1/5] 等待 document.readyState=complete ...")

    page.wait_for_function(
        "() => document.readyState === 'complete'",
        timeout=120_000,
    )

    print("[2/5] 等待页面中出现有效 Canvas ...")

    try:
        page.wait_for_function(
            """
            () => {
                const canvases = Array.from(
                    document.querySelectorAll("canvas")
                );

                return canvases.some(canvas => {
                    const rect = canvas.getBoundingClientRect();

                    return (
                        canvas.width > 100 &&
                        canvas.height > 100 &&
                        rect.width > 100 &&
                        rect.height > 100
                    );
                });
            }
            """,
            timeout=120_000,
        )

    except PlaywrightTimeoutError:
        print(
            "[WARN] 没有等到明显的 Canvas，继续执行。"
        )

    print("[3/5] 触发 resize，让 Ares 重新计算布局 ...")

    page.evaluate(
        """
        () => {
            window.dispatchEvent(new Event("resize"));

            setTimeout(
                () => window.dispatchEvent(new Event("resize")),
                500
            );

            setTimeout(
                () => window.dispatchEvent(new Event("resize")),
                1500
            );
        }
        """
    )

    print("[4/5] 等待 Canvas 和页面尺寸稳定 ...")

    try:
        page.wait_for_function(
            """
            async () => {
                function snapshot() {
                    const canvases = Array.from(
                        document.querySelectorAll("canvas")
                    );

                    const rects = canvases.map(canvas => {
                        const rect = canvas.getBoundingClientRect();

                        return [
                            Math.round(rect.x),
                            Math.round(rect.y),
                            Math.round(rect.width),
                            Math.round(rect.height),
                            canvas.width,
                            canvas.height,
                        ];
                    });

                    return JSON.stringify({
                        innerWidth: window.innerWidth,
                        innerHeight: window.innerHeight,
                        bodyWidth: document.body.clientWidth,
                        bodyHeight: document.body.clientHeight,
                        rects,
                    });
                }

                const first = snapshot();

                await new Promise(
                    resolve => setTimeout(resolve, 1200)
                );
                const second = snapshot();

                await new Promise(
                    resolve => setTimeout(resolve, 1200)
                );
                const third = snapshot();

                return first === second && second === third;
            }
            """,
            timeout=60_000,
        )

    except PlaywrightTimeoutError:
        print("[WARN] 页面尺寸没有完全稳定，继续截图。")

    print("[5/5] 额外等待 3 秒，让地图和轨迹完成渲染 ...")
    page.wait_for_timeout(3000)


def print_page_info(page):
    """打印页面和 Canvas 尺寸信息。"""

    info = page.evaluate(
        """
        () => {
            const canvases = Array.from(
                document.querySelectorAll("canvas")
            ).map((canvas, index) => {
                const rect = canvas.getBoundingClientRect();

                return {
                    index,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    cssWidth: Math.round(rect.width),
                    cssHeight: Math.round(rect.height),
                    canvasWidth: canvas.width,
                    canvasHeight: canvas.height,
                };
            });

            return {
                url: location.href,
                title: document.title,
                readyState: document.readyState,
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                outerWidth: window.outerWidth,
                outerHeight: window.outerHeight,
                devicePixelRatio: window.devicePixelRatio,
                bodyWidth: document.body.clientWidth,
                bodyHeight: document.body.clientHeight,
                canvasCount: canvases.length,
                canvases,
            };
        }
        """
    )

    print("[INFO] 页面尺寸信息：")
    print(info)


def take_screenshot(browser, keep_open: bool):
    """
    使用本地登录态打开页面并截图。

    注意：截图只保存到本地，不会执行 SCP 上传。
    """

    if not STATE_FILE.exists():
        raise FileNotFoundError(
            f"没有找到本地登录态：{STATE_FILE.resolve()}\n"
            "请先运行：\n"
            "  python ares_screenshot.py --mode login"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = OUT_DIR / f"ares_{timestamp}.png"

    context = browser.new_context(
        storage_state=str(STATE_FILE),
        ignore_https_errors=True,
        no_viewport=True,
    )

    page = context.new_page()

    try:
        print("[OPEN] 使用本地登录态打开 Ares Studio ...")

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=120_000,
        )

        # 等待 SPA 展示主页面或错误信息。
        page.wait_for_timeout(1500)

        has_service_error = check_page_error(page)

        if not has_service_error:
            wait_for_ares_loaded(page)

        print_page_info(page)

        print(f"[SHOT] 保存本地截图：{screenshot_path.resolve()}")

        page.screenshot(
            path=str(screenshot_path),
            full_page=False,
        )

        if not screenshot_path.exists():
            raise RuntimeError("截图文件生成失败。")

        print(f"[SHOT] 截图完成：{screenshot_path.resolve()}")
        print("[SHOT] 截图不会上传到远端。")

        if keep_open:
            input("按 Enter 关闭浏览器...")

    finally:
        context.close()


def main():
    args = parse_args()

    print("[CONFIG] 当前配置：")
    print(f"[CONFIG] mode              = {args.mode}")
    print(f"[CONFIG] chrome path       = {args.chrome_path}")
    print(f"[CONFIG] local state       = {STATE_FILE.resolve()}")
    print(f"[CONFIG] ssh host          = {args.ssh_host}")
    print(f"[CONFIG] remote state      = {args.remote_state_path}")
    print(f"[CONFIG] skip state upload = {args.skip_state_upload}")
    print(f"[CONFIG] batch mode        = {args.batch_mode}")
    print()

    # 只上传已有登录态，不需要启动浏览器。
    if args.mode == "upload-state":
        remote_target = upload_login_state(
            state_file=STATE_FILE,
            ssh_host=args.ssh_host,
            remote_state_path=args.remote_state_path,
            batch_mode=args.batch_mode,
        )

        print()
        print(f"[DONE] 登录态已上传：{remote_target}")
        return

    with sync_playwright() as playwright:
        browser = launch_browser(
            playwright,
            chrome_path=args.chrome_path,
        )

        try:
            if args.mode == "login":
                generate_login_state(
                    browser=browser,
                    ssh_host=args.ssh_host,
                    remote_state_path=args.remote_state_path,
                    skip_state_upload=args.skip_state_upload,
                    batch_mode=args.batch_mode,
                )

            elif args.mode == "shot":
                take_screenshot(
                    browser=browser,
                    keep_open=args.keep_open,
                )

            elif args.mode == "auto":
                if not STATE_FILE.exists():
                    print(
                        "[AUTO] 没有找到本地登录态，"
                        "先登录、保存并上传。"
                    )

                    generate_login_state(
                        browser=browser,
                        ssh_host=args.ssh_host,
                        remote_state_path=args.remote_state_path,
                        skip_state_upload=args.skip_state_upload,
                        batch_mode=args.batch_mode,
                    )
                else:
                    print(
                        f"[AUTO] 已找到本地登录态："
                        f"{STATE_FILE.resolve()}"
                    )

                take_screenshot(
                    browser=browser,
                    keep_open=args.keep_open,
                )

        finally:
            browser.close()


if __name__ == "__main__":
    main()