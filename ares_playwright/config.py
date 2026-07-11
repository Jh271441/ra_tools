from pathlib import Path


ARES_URL = (
    "https://voyager.intra.xiaojukeji.com/static/ares-studio/"
    "?ds=voy-ws-car"
    "&ds.start=1783332960157"
    "&ds.end=1783333000157"
    "&ds.trip_id=10315_20260706_180656"
    "&ds.server="
    "&layoutId=9e3be845-41e7-485d-90d3-d46a46a5ab19"
    "&time=2026-07-06T10%3A16%3A20.256999998Z"
)

LOGIN_HOST = "me.xiaojukeji.com"
TARGET_HOST = "voyager.intra.xiaojukeji.com"
AUTH_CHECK_URL = ARES_URL

DEFAULT_CHROME_PATH = "/usr/bin/google-chrome"
DEFAULT_SSH_HOST = "cloud_server"
DEFAULT_REMOTE_STATE_PATH = "/tmp/ares_storage_state.json"

STATE_FILE = Path("ares_storage_state.json")
SCREENSHOT_DIR = Path("playwright_screenshots")

NAVIGATION_TIMEOUT_MS = 120_000
