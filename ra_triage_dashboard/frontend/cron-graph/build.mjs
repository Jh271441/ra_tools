import { build } from 'esbuild';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
const out = '../../static/vendor/cron-graph';
mkdirSync(out, { recursive: true });
await build({ entryPoints: ['src/index.jsx'], bundle: true, minify: true, format: 'iife', globalName: 'RACronGraph', outfile: `${out}/graph.js`, legalComments: 'linked', target: ['es2022'], define: { 'process.env.NODE_ENV': '"production"' } });
const packages = ['@xyflow/react', 'elkjs', 'react', 'react-dom', 'esbuild'];
mkdirSync(`${out}/licenses`, { recursive: true });
for (const name of packages) {
  for (const filename of ['LICENSE', 'LICENSE.md', 'LICENSE.txt']) {
    try { writeFileSync(`${out}/licenses/${name.replaceAll('/', '-').replace('@', '')}.txt`, readFileSync(`node_modules/${name}/${filename}`)); break; } catch (_) {}
  }
}
const dependencies = packages.map(name => {
  const pkg = JSON.parse(readFileSync(`node_modules/${name}/package.json`, 'utf8'));
  return { name, version: pkg.version, license: pkg.license };
});
writeFileSync(`${out}/provenance.json`, JSON.stringify({ dependencies, build: 'npm ci && npm run build', artifacts: Object.fromEntries(['graph.js', 'graph.css'].map(name => [name, createHash('sha256').update(readFileSync(`${out}/${name}`)).digest('hex')])) }, null, 2) + '\n');
