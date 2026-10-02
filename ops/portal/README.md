# RA Tools 聚合入口

简洁卡片首页，提供同源 `/manual/`、`/sim/overview` 导航。独立 Nginx 监听 80，
路径原样转发到同机 8785、8787；不依赖旧 local，也不改变已有 Kylin 域名配置。

在有 Nginx、系统 Supervisor 和 sudo 权限的目标机器执行：

```bash
python3 install.py --root /持久化目录/ra-portal --port 80 --manual-port 8785 --sim-port 8787
```

`index.html`、`favicon.svg` 与 `install.py` 放在同一目录。首次部署前确认端口空闲。安装前执行
Nginx 配置检查；更新保留 nginx.previous.conf 并平滑 reload。由系统 Supervisor
的 `ra_portal_<port>` 管理启动恢复。仅代理指定前缀，其余路径返回 404。

该直接 IP 入口不注入 SSO 身份或 trusted-ingress marker，Manual 后端继续执行原有
认证与写入限制。既有 HTTPS/SSO 域名入口保持不变。

2026-09-28 部署实例：`/volume/home/services/ra-portal`，访问
`http://172.16.145.60/`。检查 `/healthz`、`/manual/`、`/sim/overview`、静态资源、
`/manual/api/session` 和 `/sim/api/health`。UI 参考旧 gateway portal，支持浅色/深色
和窄屏布局。

## 首页更新记录

2026-09-29：外观改为三段切换按钮，主题色改为四色圆点，统一置于页面右上角。
已在现有部署目录原子替换 `index.html`，未修改 Nginx 配置或重启上游服务。
服务器 HTTP 首页内容哈希与本地文件一致，`/healthz` 正常。

- SHA-256：`23129e8eef3d107cb1f9e4ff5ed769f069eac278e26ac3dc7a0e331dac3bf4e1`
- 发布记录：`/volume/home/services/ra-portal/releases/20260929T035735Z-appearance-buttons/result.json`
- 同目录 `index.previous.html` 保存旧首页，`index.html` 保存发布文件。
