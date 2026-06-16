# 通过 Tailscale 把网关暴露给所有 tailnet 设备

把本机 nginx 网关(见 [README.md](./README.md))经 Tailscale 暴露成
`http://auto-trigger/`,让 tailnet 里的所有设备(Mac / Windows / 安卓 / 云主机)都能访问。

---

## 整体架构

```
tailnet 设备 (Mac/Win/...)
        │  http://auto-trigger/  或  http://100.66.3.66/
        ▼
┌─────────────────────────────────────────────────────────────┐
│ ts-proxy 容器 (tailscale, userspace, 节点名 auto-trigger)      │
│   tailscale serve --tcp=80  →  127.0.0.1:80                    │
│        ▲                                                       │
│        │ 127.0.0.1:80                                          │
│   ts-gateway-bridge 容器 (socat, 共享 ts-proxy 网络命名空间)   │
│        socat 127.0.0.1:80  →  172.17.0.1:80 (宿主机)           │
└────────┼──────────────────────────────────────────────────────┘
         │ 172.17.0.1:80 (docker 默认 bridge 网关 = 宿主机)
         ▼
   ra-gateway-nginx 容器 (network_mode: host, 监听 :80)
         ├─ /        → 127.0.0.1:8765   (model-release 应用)
         ├─ /dcc/    → 127.0.0.1:9999   (dcc)
         └─ /tb/     → 127.0.0.1:16006  (tensorboard / ssh 隧道)
```

| 容器 | 作用 | 网络模式 |
|------|------|----------|
| `ts-proxy` | Tailscale 节点(userspace),serve 入站 + SOCKS5(1055)出站 | bridge,`-p 1055`、`-p 41641` |
| `ts-gateway-bridge` | socat,把宿主机 nginx:80 桥进 ts-proxy 命名空间 | `container:ts-proxy` |
| `ra-gateway-nginx` | 反向代理网关,按路径分发到各本地服务 | `host` |

---

## 为什么是这套结构(关键原理)

1. **Tailscale 跑在容器里且是 userspace 模式**(`TS_USERSPACE=true`,无 tun 网卡)。
   入站只能靠 `tailscale serve`,出站靠 SOCKS5(`:1055`)。

2. **`tailscale serve` 的目标只能是 `localhost/127.0.0.1`**。而 nginx 跑在宿主机、
   不在 ts-proxy 命名空间里,所以用一个 **socat 桥**把 `127.0.0.1:80` 转到宿主机
   `172.17.0.1:80`,让 nginx 在 ts-proxy 眼里「变成本地」。

3. **用 `--tcp=80`(4 层透传)而不是 `--http=80`(7 层)**:
   - `--http=80` 按 **Host 头(MagicDNS 名字)** 路由,用 IP 访问会因 `Host: 100.66.3.66`
     匹配不到 handler 而 404。
   - `--tcp=80` 不看 Host,**IP 和名字都能直连**,HTTP 路由全交给 nginx。

---

## 部署 / 复现步骤

> 前提:`ts-proxy` 容器已稳定运行(独立 `docker run` 起的,本流程不改动它),
> 后台已登录、节点名为 `auto-trigger`。
> 改名在后台 Machines → Edit machine name(`--hostname` 仅首次注册生效,不要为改名重建容器)。

### 1. nginx + socat 桥(docker compose)

`docker-compose.yml` 中的两个服务:

```yaml
services:
  nginx:
    image: nginx:stable-alpine
    container_name: ra-gateway-nginx
    network_mode: host
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    restart: unless-stopped

  # 把主机 nginx:80 桥进 ts-proxy 命名空间,供 `tailscale serve` 以 127.0.0.1:80 暴露
  ts-bridge:
    image: alpine/socat
    container_name: ts-gateway-bridge
    network_mode: "container:ts-proxy"   # 注意是 container: 引用外部容器,不是 service:
    command: -d -d TCP-LISTEN:80,bind=127.0.0.1,fork,reuseaddr TCP:172.17.0.1:80
    restart: unless-stopped
```

启动:

```bash
cd ops/gateway
docker compose up -d
```

### 2. 配置 tailscale serve(4 层透传,一次性;配置存在卷里,重启自动生效)

```bash
docker exec ts-proxy tailscale serve reset
docker exec ts-proxy tailscale serve --bg --tcp=80 tcp://127.0.0.1:80
docker exec ts-proxy tailscale serve status
```

期望输出:

```
|-- tcp://auto-trigger.tail9ceda4.ts.net:80 (TLS over TCP, tailnet only)
|-- tcp://100.66.3.66:80
|--> tcp://127.0.0.1:80
```

(`serve status --json` 应只有 `TCPForward`、没有 `TerminateTLS`,即纯透传;
状态文本里的 "TLS over TCP" 只是显示措辞,客户端用裸 HTTP 即可。)

### 3.(可选)再加一层 HTTPS,自动证书

由 Tailscale 终止 TLS(自动 Let's Encrypt 证书),后端继续给 nginx 发裸 HTTP。
可与上面的 `tcp/80` **并存**(80 留给 IP/裸 HTTP 调试,443 给正式访问)。

前提:admin 后台已开 **HTTPS Certificates**(DNS 页)+ **MagicDNS**。先探测能否签发:

```bash
docker exec ts-proxy tailscale cert auto-trigger.tail9ceda4.ts.net   # 成功写出 .crt/.key 即已开启
```

启用 HTTPS(不 reset,保留 80):

```bash
docker exec ts-proxy tailscale serve --bg --https=443 http://127.0.0.1:80
docker exec ts-proxy tailscale serve status
```

访问:`https://auto-trigger.tail9ceda4.ts.net/`(绿锁)。

> **HTTPS 只认完整 FQDN**:证书签给 `auto-trigger.tail9ceda4.ts.net`,
> 用短名 `https://auto-trigger/` 或 IP `https://100.66.3.66/` 都会证书不匹配。
> 另外 **ACL 需放行 `:443`**(同 80 的坑)。
> 关掉 HTTPS:`tailscale serve --https=443 off`。

---

## 客户端如何访问

客户端的 Tailscale 也在**容器内**跑(userspace)时,**宿主机/浏览器默认不在 tailnet 上**:

- **装原生 Tailscale 客户端**(推荐):登录同一 tailnet 后,浏览器直接 `http://auto-trigger/`。
- **走客户端本地 ts-proxy 的 SOCKS5**(`127.0.0.1:1055`):
  - 命令行:`curl -x socks5h://127.0.0.1:1055 http://auto-trigger/`
  - 浏览器:设 SOCKS5 `127.0.0.1:1055` 并开启**远端 DNS(socks5h)**,
    建议用 SwitchyOmega 只对 `*.ts.net` 和 `100.64.0.0/10` 走该代理。

> ⚠️ 若机器上开着系统代理(如 Clash `127.0.0.1:7890`),浏览器/curl 会把
> `http://auto-trigger/` 丢给该代理,代理不认 tailnet 名字 → 打不开。
> 需把 tailnet 加入代理 bypass(`*.ts.net`、`100.64.0.0/10`),
> 或命令行加 `--noproxy '*'`(注意:`--noproxy` 会同时取消 `-x`,二者别混用)。

---

## 新增一个服务

只改 `nginx.conf` 加一段 location,**tailscale / socat 都不用动**:

```nginx
location /myapp/ {
    proxy_set_header X-Forwarded-Prefix /myapp;
    proxy_pass http://127.0.0.1:<端口>/;
}
```

然后 `docker compose exec nginx nginx -s reload`。

---

## 排错速查

| 现象 | 原因 | 解决 |
|------|------|------|
| `tailscale ping` 通但 TCP 连不上 | **ACL 包过滤**挡了端口(ping 走 disco 层不过 ACL,TCP 过) | 后台 Access controls 放行 `dst` 的 `:80`(或 `*:*`) |
| 用名字能开、用 `IP/` 打不开 | `--http` 模式按 Host 路由,IP 匹配不到 | 改用 `--tcp`(本文档已用),或 `curl -H "Host: auto-trigger"` |
| 浏览器打不开但 `curl --noproxy '*'` 能通 | 系统代理(7890)劫持了请求 | 代理 bypass 加 tailnet,或浏览器走 SOCKS5 1055 |
| 名字解析不了 | MagicDNS 未生效 | 后台开 MagicDNS;客户端 `tailscale set --accept-dns` |
| 在网关主机本机 curl 自己的 serve 总失败 | 节点**无法回环访问自身 serve**,属正常 | 必须从**别的** tailnet 节点测 |
| serve 配置丢失 | — | 配置存于 `tailscale_data` 卷;`serve status` 复查,必要时重跑第 2 步 |

---

## 现网参数速记

- tailnet:`tail9ceda4.ts.net`
- 网关节点:`auto-trigger`(`100.66.3.66`)
- ts-proxy SOCKS5:`:1055`,WireGuard:`:41641/udp`
- nginx 路由:`/`→8765、`/dcc/`→9999、`/tb/`→16006
