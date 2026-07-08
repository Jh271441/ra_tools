# CPA Local Setup

This folder keeps only the local CPA service wiring and the browser-side exporter.

## Files

- `docker-compose.yml`: runs `eceasy/cli-proxy-api` as `cpa-server`.
- `config.example.yaml`: safe template for local `config.yaml`.
- `config.yaml`: local secret config, ignored by git.
- `auth-dir/`: local CPA account state, tokens, and request logs, ignored by git.
- `export_script.js`: paste into the ChatGPT browser console after switching to the target workspace. It exports one CPA `codex-*.json` for the currently selected session.

## Export Current Workspace

1. Open ChatGPT in the browser.
2. Switch to the target workspace/account.
3. Paste and run `export_script.js` in the browser console.
4. Upload the downloaded `codex-*.json` in the CPA management UI.

CPA watches `auth-dir/`, so uploads take effect without restarting the container.
Do not delete files from `auth-dir/` while relying on the currently loaded accounts; CPA may treat deletion as an account removal.

## Local Config

Create a local config from the template:

```bash
cp ops/cpa/config.example.yaml ops/cpa/config.yaml
```

Then edit `secret-key`, `api-keys`, and proxy settings locally.
