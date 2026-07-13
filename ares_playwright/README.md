# Ares Playwright 工具

Ares Studio 登录态校验与截图工具。通过 BrowserContext 和真实 Ares 页面访问验证
storage state；只有验证为 `VALID` 的状态才会截图或上传。

（旧的 `scripts/playwright_test.py` 已删除，统一使用本包。）

## 模块

- `auth.py`：JSON 静态检查、登录页识别、真实状态验证
- `login.py`：凭证读取、自动登录、状态保存、保存后复验
- `upload.py`：SCP 临时文件上传与 SSH 原子替换
- `screenshot.py`：Ares 加载等待和本地截图
- `cli.py`：命令行参数与模式编排

## 使用

从仓库根目录执行：

```bash
.venv/bin/python -m ares_playwright --mode login
.venv/bin/python -m ares_playwright --mode auto
.venv/bin/python -m ares_playwright --mode auto --force-login
.venv/bin/python -m ares_playwright --mode validate-state
.venv/bin/python -m ares_playwright --mode upload-state
.venv/bin/python -m ares_playwright --mode shot
```

### SSH 无界面登录

在没有 `DISPLAY` 的 SSH 会话中使用 headless 模式。终端会隐藏密码输入，Playwright
等待 Voyager 异步跳转到 SSO 后，自动填写账号密码并点击登录：

```bash
.venv/bin/python -m ares_playwright --mode login --headless --no-proxy
```

`--no-proxy` 只让此次 Chrome 进程直连，不修改 shell 或系统代理。当前环境通过
`127.0.0.1:7890` 访问 Voyager 可能出现 `net::ERR_CONNECTION_CLOSED`，此时必须使用
该参数。

登录成功后，工具保存并复验 `ares_storage_state.json`。默认还会通过 SCP 上传到
`cloud_server:/tmp/ares_storage_state.json`；当前机器不需要上传时添加
`--skip-state-upload`。

### Headless 截图

使用已有登录态直接截图：

```bash
.venv/bin/python -m ares_playwright --mode shot --headless --no-proxy
```

检查登录态、必要时重新登录并截图：

```bash
.venv/bin/python -m ares_playwright --mode auto --headless --no-proxy
```

截图保存在 `playwright_screenshots/`，不会上传。headless 模式下不要使用
`--keep-open`，因为没有可见浏览器窗口。

### 无人值守

无人值守模式要求通过环境变量提供账号密码：

```bash
export ARES_USERNAME="你的账号"
export ARES_PASSWORD="你的密码"
.venv/bin/python -m ares_playwright --mode auto --headless --no-proxy --batch-mode --non-interactive
unset ARES_PASSWORD
```

账号密码只用于本次登录，不会写入 storage state；storage state 中保存的是登录后的
Cookie 和站点存储。若 SSO 要求验证码、MFA 或设备确认，无界面模式会失败，需要在有
界面的浏览器中完成该次安全验证。

不要将账号、密码或 `ares_storage_state.json` 提交到 Git。该状态文件和截图目录已在
`.gitignore` 中排除。

## 测试

```bash
.venv/bin/python -m unittest discover -s ares_playwright/tests -v
```
