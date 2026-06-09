# Phase 0 · Vite + React 脚手架

## Context

`model_release_pipeline/web_static/` 当前是原生 ESM + 手写 CSS 的前端，约 **1800 行 JS / 2900 行 CSS / 13 个模块 / 8 个样式表**。最重的两个文件 `modules/workflow.js` (473 行) 与 `modules/workflowController.js` (527 行) 已经到了"原生 DOM 字符串拼接 + 手动状态同步"难以维护的规模，每加一个交互都要在多个模块里串改、容易漏渲染。

本次重构整体目标是迁移到 **React + Vite + TypeScript**，引入 HMR、组件化、类型系统三件事来恢复迭代速度。整体计划分 7 个 Phase，**本文件只覆盖 Phase 0：脚手架**。Phase 0 的产出是一个可独立启动、可调通后端 API 的最小 React 工程，旧 `web_static/` 一行不动，双轨并行可随时回退。

后续 Phase 1-6（API 客户端、布局、Runs、Workflow、Jobs/Logs、切换部署）在 Phase 0 验收通过后再分别规划。

## 决策点（已确认）

| 项 | 选择 | 备注 |
|---|---|---|
| 包管理器 | **npm 10.9.2** | 单人 + 单项目，零额外安装步骤 |
| Node 版本 | **v22.17.0**（已装） | 满足 Vite 5 ≥ 18 要求 |
| 框架 | **React 18 + TypeScript** | 之前确认 |
| 构建工具 | **Vite 5** | 之前确认 |
| 后端端口 | **8765** | `model_release_pipeline/onboard/parser.py:286` 默认值 |
| 前端 dev 端口 | **5173** | Vite 默认 |
| 旧前端 | **保持不动** | `web_static/` 继续由 `web_app.py:43,510-516` 提供 |
| `node_modules` / `dist` | **不入库** | 加到 `.gitignore` |

## Scope（本 Phase 只做这些）

**做**：
- 在 `model_release_pipeline/web_frontend/` 下搭起 Vite + React + TS 工程
- 配 dev proxy：前端 `fetch('/api/...')` → `http://127.0.0.1:8765`
- 跑通"前端启动 + 调一次真实 `/api/runs` + HMR 生效"
- 拷一份 `favicon.svg` 进 `public/`
- 更新根 `.gitignore`

**不做**（留给后续 Phase）：
- 不迁任何业务模块、不接路由、不接状态管理库（Zustand / React Query）
- 不动 `web_app.py`、`web/`、`state_store.py`、`web_static/`
- 不写组件、不迁 CSS、不接 lucide-react

## 完成定义 (DoD)

1. `cd model_release_pipeline/web_frontend && npm run dev` 启动成功，浏览器打开 `http://localhost:5173` 不报错
2. 首页能展示一行从 `/api/runs` 拿到的真实数据（例如："Loaded N releases from /api/runs."）
3. 改 `App.tsx` 一个字保存 → 浏览器**不刷新**就更新（验证 HMR）
4. `npm run build` 成功，产物在 `web_frontend/dist/`
5. `python -m model_release_pipeline.web_app`（或现有启动方式）启动后，**旧 web_static/ 前端依然能正常用**
6. `git status` 不显示 `node_modules/` 或 `dist/`

## 目录结构（Phase 0 结束后）

```
model_release_pipeline/
├── web_app.py                   # 不动
├── web/                         # 不动
├── web_static/                  # 不动（旧前端继续工作）
└── web_frontend/                # ← 新增
    ├── .gitignore               # 局部（dist, .vite, node_modules）
    ├── package.json
    ├── package-lock.json
    ├── tsconfig.json
    ├── tsconfig.node.json
    ├── vite.config.ts
    ├── index.html
    ├── public/
    │   └── favicon.svg          # 从 web_static/favicon.svg 拷贝
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/
        │   └── client.ts        # fetchJson 雏形
        ├── types/
        │   └── api.ts           # Run 类型占位
        └── styles/
            └── globals.css      # 极简 reset
```

## 关键文件内容

### `model_release_pipeline/web_frontend/package.json`
```json
{
  "name": "model-release-frontend",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "typescript": "^5.6.3",
    "vite": "^5.4.10"
  }
}
```

### `model_release_pipeline/web_frontend/vite.config.ts`
```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
```

### `model_release_pipeline/web_frontend/tsconfig.json`
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

### `model_release_pipeline/web_frontend/tsconfig.node.json`
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

### `model_release_pipeline/web_frontend/index.html`
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Release Agent (dev)</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

### `model_release_pipeline/web_frontend/src/main.tsx`
```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/globals.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

### `model_release_pipeline/web_frontend/src/App.tsx`
```tsx
import { useEffect, useState } from 'react';
import { fetchJson } from './api/client';
import type { Run } from './types/api';

export default function App() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchJson<{ runs: Run[] }>('/api/runs')
      .then((data) => setRuns(data.runs ?? []))
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main style={{ padding: 24, fontFamily: 'system-ui' }}>
      <h1>Release Agent — Vite Scaffold</h1>
      {error && <p style={{ color: 'crimson' }}>API error: {error}</p>}
      {runs === null && !error && <p>Loading…</p>}
      {runs && <p>Loaded <strong>{runs.length}</strong> releases from /api/runs.</p>}
    </main>
  );
}
```

### `model_release_pipeline/web_frontend/src/api/client.ts`
对应旧文件 `model_release_pipeline/web_static/modules/api.js` 的最小子集，Phase 1 再补全 `postJson` / `patchJson`。
```ts
export async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}
```

### `model_release_pipeline/web_frontend/src/types/api.ts`
仅放占位，Phase 1 从 `model_release_pipeline/state_store.py:21-37`（`StateStore.create` 的 record 结构）和 `model_release_pipeline/web/actions.py` 反推完整类型。
```ts
export interface Run {
  release_id: string;
  status?: string;
  description?: string;
}
```

### `model_release_pipeline/web_frontend/src/styles/globals.css`
```css
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; }
```

### `model_release_pipeline/web_frontend/.gitignore`
```
node_modules
dist
.vite
*.local
.DS_Store
```

### 根 `.gitignore` 追加
追加到现有 `/home/didi/workspace/ra_tools/.gitignore`（如未配置则新建条目）：
```
model_release_pipeline/web_frontend/node_modules/
model_release_pipeline/web_frontend/dist/
```

## 执行步骤

| Step | 动作 | 验证 |
|---|---|---|
| 1 | `mkdir -p model_release_pipeline/web_frontend/{public,src/api,src/types,src/styles}` | `ls model_release_pipeline/web_frontend` |
| 2 | 创建上述 11 个文件（package.json / vite.config.ts / tsconfig × 2 / index.html / .gitignore / main.tsx / App.tsx / client.ts / api.ts / globals.css） | `ls -R model_release_pipeline/web_frontend` |
| 3 | `cp model_release_pipeline/web_static/favicon.svg model_release_pipeline/web_frontend/public/` | favicon 存在 |
| 4 | 追加根 `.gitignore` | `git status` 不显示 `web_frontend/node_modules` |
| 5 | `cd model_release_pipeline/web_frontend && npm install` | 0 vulnerabilities，无 error |
| 6 | 确认后端 8765 在跑（`curl -s http://127.0.0.1:8765/api/runs \| head -c 80`） | 返回 JSON |
| 7 | `npm run dev` | 终端打印 `Local: http://localhost:5173/` |
| 8 | 浏览器打开 `http://localhost:5173` | 看到 "Loaded N releases from /api/runs." |
| 9 | 改 `App.tsx` 标题文字保存 | 浏览器**不刷新**自动更新 → HMR 验证通过 |
| 10 | 停 dev server，`npm run build` | `dist/index.html`、`dist/assets/*.js` 生成；无 TS 错误 |
| 11 | 启动后端 `python -m model_release_pipeline.web_app` 访问 `http://127.0.0.1:8765` | 旧 web_static/ 前端正常 |
| 12 | `git status` | 仅显示新增的 `web_frontend/` 受控文件，无 `node_modules`/`dist` |

## 验证 (Verification)

**功能验证**：
- 步骤 8 看到真实 release 数 → 证明 Vite proxy 把 `/api/runs` 正确转发到 8765
- 步骤 9 HMR 生效 → 证明开发体验升级达成
- 步骤 10 build 成功 → 证明生产构建路径通
- 步骤 11 旧前端可用 → 证明零回归

**Git 卫生**：
- `git status` 输出应该是 `web_frontend/` 下的源文件（不含 `node_modules`、`dist`、`.vite`）+ 根 `.gitignore` 修改

**端口冲突应对**（不在 DoD 内，但记录）：
- 若 8765 已占用：临时改后端 `--port 8766` 启动，同步改 `vite.config.ts` 的 proxy target
- 若 5173 已占用：`strictPort: true` 会直接报错，改 `vite.config.ts` 的 `server.port`

## 风险与回滚

| 风险 | 概率 | 应对 |
|---|---|---|
| npm registry 网络慢/装不动 | 中 | 配镜像 `npm config set registry https://registry.npmmirror.com` |
| 后端 8765 未启动导致首页 API 错误 | 中 | 步骤 6 先 curl 验证；错误信息会显示在 App.tsx 的 error 区，便于排查 |
| 弄坏旧前端 | **极低** | 完全隔离，回滚 = `rm -rf model_release_pipeline/web_frontend` + 还原 `.gitignore` |
| TS 严格模式报错卡 build | 低 | `package.json` 的 `dev` 不跑 tsc，遇到再调整 tsconfig |

## 下一步衔接

Phase 0 通过后，Phase 1 开始：
- 把 `model_release_pipeline/web_static/modules/api.js` 的 `postJson` / `patchJson` 迁到 `client.ts`
- 根据 `model_release_pipeline/state_store.py` 和 `model_release_pipeline/web/actions.py` 补全 `types/api.ts` 的所有接口
- 引入 `@tanstack/react-query`（可选）作为数据层
