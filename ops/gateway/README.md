# Nginx Gateway

This gateway exposes local RA tools through one HTTP entrypoint on port 80.
Colleagues can access services with the development machine IP and path prefixes, without typing service ports.

> 想把这个网关经 Tailscale 暴露给所有 tailnet 设备(`http://auto-trigger/`)?见 [TAILSCALE.md](./TAILSCALE.md)。

## Routes

- `http://<dev-machine-ip>/` -> static tool portal
- `http://<dev-machine-ip>/release/` -> model-release at `127.0.0.1:8765`
- `http://<dev-machine-ip>/sim/` -> RA sim repro dashboard static build
- `http://<dev-machine-ip>/sim/api/` -> RA sim repro API at `127.0.0.1:8000/api/`
- `http://<dev-machine-ip>/cpa/` -> CPA management UI at `127.0.0.1:8317`
- `http://<dev-machine-ip>/cpa/v1/` -> CPA OpenAI-compatible API at `127.0.0.1:8317/v1/`
- `http://<dev-machine-ip>/v1/` -> lingma-proxy OpenAI-compatible API at `127.0.0.1:8095/v1/`
- `http://<dev-machine-ip>/dcc/` -> DCC at `127.0.0.1:9999`
- `http://<dev-machine-ip>/tb/` -> TensorBoard tunnel at `127.0.0.1:16006`

## CPA Subpath Notes

The CPA management frontend defaults its API base to the current scheme, host, and port, without
the `/cpa` mount path. Its management calls therefore use absolute `/v0/management/*` paths and
its model list uses absolute `/v1/models`.

The gateway forwards only `/v0/management/*` to CPA. For the conflicting `/v1/models` path, it
uses the CPA management page Referer to send that browser request to CPA; requests without that
Referer keep the existing lingma-proxy authentication and upstream. Do not globally remap root
`/v1/models` to CPA.

## DCC Path Prefix Notes

DCC currently serves its frontend and API from root paths such as `/chunk-*.js`, `/api/dashboard`, and `/plugins`.
The gateway keeps DCC under `/dcc/` by rewriting DCC HTML/JS/manifest responses with `sub_filter`, injecting React Router `basename="/dcc"`, and forwarding DCC upstream requests with `Host`, `Origin`, and `Referer` values that match direct `127.0.0.1:9999` access.

If DCC is rebuilt to natively support a `/dcc` base path, remove the DCC `sub_filter` rules and upstream header overrides from `nginx.conf`.

## Start

```bash
cd ops/gateway
docker compose up -d
```

## Validate

```bash
docker compose config
docker compose exec nginx nginx -t
```

## Reload

```bash
docker compose exec nginx nginx -s reload
```

## Logs

```bash
docker compose logs -f
```

## Local Smoke Tests

```bash
curl -sS http://127.0.0.1/
curl -sS http://127.0.0.1/dcc/
curl -sS http://127.0.0.1/tb/
```

## Service Bindings

For a tighter first-hop setup, run the upstream services on localhost:

```bash
python -m model_release_pipeline.cli web --host 127.0.0.1 --port 8765
ssh -N -T -L 127.0.0.1:16006:127.0.0.1:6006 luban_1_card
```

If DCC supports binding its host, prefer `127.0.0.1:9999`.

The current gateway strips `/tb/` before proxying to `127.0.0.1:16006`, so it works with a TensorBoard instance served from `/`.
If TensorBoard static assets or redirects break, change the `/tb/` `proxy_pass` to `http://127.0.0.1:16006` without the trailing slash so Nginx preserves the prefix, then start TensorBoard with a matching path prefix:

```bash
tensorboard --host 127.0.0.1 --port 6006 --path_prefix /tb
```

Use either the strip-prefix proxy with a root-mounted TensorBoard, or the prefix-preserving proxy with `--path_prefix /tb`; mixing those modes will usually produce 404s.

## Lessons Learned: `{"detail":"Not Found"}` from an upstream

**Symptom.** A request through the gateway returns `{"detail":"Not Found"}`, while hitting the
backend directly (e.g. `http://10.152.44.17:8009/v1/chat/completions`) works fine.

**Diagnosis — read the 404, don't guess.** vLLM (and any FastAPI app) returns exactly
`{"detail":"Not Found"}` for an unknown path. Getting that body *through the gateway* means the
request **already reached the backend** — it was authenticated and routed — but arrived on the
**wrong path**. So it is neither an auth problem nor a connectivity problem; it is a path-rewrite
problem in the gateway.

Confirm it in one shot — append garbage to the path on the backend and compare:

```bash
curl http://10.152.44.17:8009/v1/__nope__
# -> {"detail":"Not Found"}   (identical body == backend reached, path is what's wrong)
```

Contrast with the two failure modes that are NOT this:
- empty/refused/`Connection refused` -> gateway can't reach the upstream (network/port).
- a body like `{"message":"No API key found in request"}` -> auth layer rejected it (wrong header
  name/position; for our setup the working header turned out to be `apikey:`, not
  `Authorization: Bearer`).

**Root cause — `proxy_pass` trailing slash.** In nginx, a trailing slash on `proxy_pass` makes it
**strip the matched `location` prefix**; no trailing slash **preserves the full path**:

| `location` | `proxy_pass` | request `/v1/chat/completions` arrives at backend as |
|---|---|---|
| `/llm/` | `http://127.0.0.1:8009/` | `/chat/completions`  ❌ (prefix stripped -> FastAPI 404) |
| `/llm/` | `http://127.0.0.1:8009`  | `/llm/v1/chat/completions` ❌ (wrong path) |
| `/`     | `http://127.0.0.1:8009`  | `/v1/chat/completions` ✅ (path preserved) |

**Fix.** For an OpenAI-compatible backend that serves at `/v1/...`, route it so the full
`/v1/...` path reaches the backend unchanged — either mount it at `/` with a slash-less
`proxy_pass`, or keep the prefix in the upstream path. Do not strip a prefix the backend doesn't
know about. (Same trailing-slash rule already bit the `/tb/` TensorBoard route above.)

**Side note — don't leave the backend bare.** `10.152.44.17:8009` answered with no auth at all.
If that IP is reachable on the intranet, it bypasses every gateway control. Either bind vLLM to
localhost and expose it only through the gateway, or start vLLM with its own key
(`vllm serve ... --api-key <key>`, then call with `Authorization: Bearer <key>`).
