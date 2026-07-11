from pathlib import Path


def launch_browser(
    playwright,
    chrome_path: str,
    headless: bool = False,
    no_proxy: bool = False,
):
    """Launch the locally installed Google Chrome."""
    chrome = Path(chrome_path)
    if not chrome.is_file():
        raise FileNotFoundError(
            f"没有找到 Chrome：{chrome_path}\n"
            "请用 which google-chrome 查找路径，再通过 --chrome-path 指定。"
        )

    args = ["--start-maximized", "--window-size=2560,1440"]
    if no_proxy:
        args.append("--no-proxy-server")

    return playwright.chromium.launch(
        executable_path=str(chrome),
        headless=headless,
        args=args,
    )
