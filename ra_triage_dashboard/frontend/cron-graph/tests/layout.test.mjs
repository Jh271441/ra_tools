import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import { layout, TASK_WIDTH, TASK_HEIGHT } from '../src/layout.mjs';

function modelFor(locale, lane = '', kind = 'daily') {
  const ctx = vm.createContext({ window: {}, document: { addEventListener() {} }, state: {}, uiText: (zh, en) => locale === 'en' ? en : zh, $: () => null, Date });
  for (const file of ['daily-cron.js', 'daily-cron-graph.js']) vm.runInContext(readFileSync(new URL(`../../../static/js/${file}`, import.meta.url), 'utf8'), ctx);
  // Screenshot case: main acquisition gap, successful Orion retry, no local receipt.
  const data = { overview: { collected_at: Date.now() / 1000, daily: { runs: [{ id: 'daily-2026-10-19', target_date_cst: '2026-10-19', state: 'complete_with_gaps', selected: 256, inferred: 255, published: 255, verified: 255, skipped: 1 }] } }, media_daily: { runs: [{ day: '2026-10-19', selected: 103, verified: 103, imported: 103, assigned: 103, camera_verified: 103, bev_verified: 103, state: 'complete', original_orion_failed: 1, retry_state: 'completed', retry_completed: 1 }] } };
  ctx.input = kind === 'daily' ? data : {states:{published:100},media:{selected:103,verified:100,
    closeup:{receipt_status:'ready',verified:99,fallback:{verified:1,registered:3,source_blocked:2}}},datasets:[]};
  ctx.lane = lane;
  return JSON.parse(vm.runInContext(`JSON.stringify(${kind === 'daily' ? 'buildDailyCronGraph' : 'buildIncrementalCronGraph'}(input, lane))`, ctx));
}

function samePoint(a, b) {
  assert.ok(Math.abs(a.x - b.x) < 0.001 && Math.abs(a.y - b.y) < 0.001, 'path endpoint must match its visible handle');
}

function intersects(a, b) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

function segmentHitsRect(a, b, rect) {
  if (Math.abs(a.x - b.x) < 0.001) return a.x > rect.x && a.x < rect.x + rect.width && Math.max(a.y, b.y) > rect.y && Math.min(a.y, b.y) < rect.y + rect.height;
  assert.ok(Math.abs(a.y - b.y) < 0.001, 'routed segments must be orthogonal');
  return a.y > rect.y && a.y < rect.y + rect.height && Math.max(a.x, b.x) > rect.x && Math.min(a.x, b.x) < rect.x + rect.width;
}

for (const locale of ['zh', 'en']) {
  for (const kind of ['daily','incremental']) for (const lane of ['', 'main', 'media']) {
    test(`${locale} ${kind} ${lane || 'combined'}: routes and labels clear task cards`, async () => {
      const model = modelFor(locale, lane, kind);
      const geometry = await layout(model);
      const lanes = new Map(geometry.sizes.map(l => [l.id, l]));
      const tasks = geometry.positions.map(p => ({ ...p, x: p.x + lanes.get(p.parentId).x, y: p.y + lanes.get(p.parentId).y, width: TASK_WIDTH, height: TASK_HEIGHT }));
      assert.equal(tasks.length, model.lanes.flatMap(l => l.nodes).length);
      assert.equal(geometry.edges.length, model.edges.length);
      for (const [i, task] of tasks.entries()) {
        for (const other of tasks.slice(i + 1)) assert.ok(!intersects(task, other), `${task.id} overlaps ${other.id}`);
      }
      const labels = [];
      for (const edge of geometry.edges) {
        const original = model.edges.find(e => e.id === edge.id);
        const source = tasks.find(n => n.id === original.source), target = tasks.find(n => n.id === original.target);
        samePoint(edge.points[0], { x: source.x + TASK_WIDTH, y: source.y + source.ports.find(p => p.id === edge.sourceHandle).y });
        samePoint(edge.points.at(-1), { x: target.x, y: target.y + target.ports.find(p => p.id === edge.targetHandle).y });
        for (let i = 1; i < edge.points.length; i++) {
          for (const task of tasks.filter(t => t !== source && t !== target)) {
            const padded = { ...task, x: task.x - 4, y: task.y - 4, width: task.width + 8, height: task.height + 8 };
            assert.ok(!segmentHitsRect(edge.points[i - 1], edge.points[i], padded), `${edge.id} crosses ${task.id}`);
          }
        }
        if (original.label) {
          assert.ok(edge.label, `${edge.id} lost its label`);
          const box = { ...edge.label, x: edge.label.x - edge.label.width / 2, y: edge.label.y - edge.label.height / 2 };
          labels.push({ ...box, id: edge.id });
          for (const task of tasks) assert.ok(!intersects(box, task), `${edge.id} label overlaps ${task.id}`);
          if (source.parentId !== target.parentId) {
            for (const group of geometry.sizes) assert.ok(!intersects(box, group), 'receipt label must stay clear of lane borders');
          }
        }
      }
      for (const [i, label] of labels.entries()) {
        for (const other of labels.slice(i + 1)) assert.ok(!intersects(label, other), `${label.id} label overlaps ${other.id}`);
        for (const edge of geometry.edges.filter(e => e.id !== label.id)) {
          for (let j = 1; j < edge.points.length; j++) assert.ok(!segmentHitsRect(edge.points[j - 1], edge.points[j], label), `${edge.id} crosses ${label.id} label`);
        }
      }
      // Separate branch ports prevent colored paths being painted on one another.
      for (const [i, edge] of geometry.edges.entries()) for (const other of geometry.edges.slice(i + 1)) {
        for (let j = 1; j < edge.points.length; j++) for (let k = 1; k < other.points.length; k++) {
          const a = edge.points[j - 1], b = edge.points[j], c = other.points[k - 1], d = other.points[k];
          const horizontal = Math.abs(a.y - b.y) < 0.001 && Math.abs(c.y - d.y) < 0.001 && Math.abs(a.y - c.y) < 0.001 && Math.min(Math.max(a.x, b.x), Math.max(c.x, d.x)) - Math.max(Math.min(a.x, b.x), Math.min(c.x, d.x)) > 1;
          const vertical = Math.abs(a.x - b.x) < 0.001 && Math.abs(c.x - d.x) < 0.001 && Math.abs(a.x - c.x) < 0.001 && Math.min(Math.max(a.y, b.y), Math.max(c.y, d.y)) - Math.max(Math.min(a.y, b.y), Math.min(c.y, d.y)) > 1;
          assert.ok(!horizontal && !vertical, `${edge.id} shares a segment with ${other.id}`);
        }
      }
    });
  }
}
