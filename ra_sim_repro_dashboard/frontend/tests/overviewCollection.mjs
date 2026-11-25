import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

// Render the actual component and translations using synthetic data only.
const root = fileURLToPath(new URL('..', import.meta.url));
const compiled = await build({
  stdin: {
    contents: `import React from 'react';
    import {renderToStaticMarkup} from 'react-dom/server';
    import {Overview} from './src/components/Overview';
    import './src/i18n';
    import i18n from 'i18next';
    export async function render(summary,comparison,language='zh',evaluationBasis=false) {
      await i18n.changeLanguage(language);
      return renderToStaticMarkup(React.createElement(Overview,{summary,comparison,evaluationBasis,onOpenIssues(){},onOpenCurrent(){}}));
    }`,
    resolveDir: root,
    loader: 'tsx',
  },
  bundle: true,
  write: false,
  platform: 'node',
  format: 'cjs',
  external: ['react', 'react-dom/server', 'react-i18next', 'i18next'],
  logLevel: 'silent',
});
globalThis.localStorage = { getItem: () => null };
const loaded = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(
  createRequire(import.meta.url),
  loaded,
  loaded.exports,
);
const { render } = loaded.exports;
const scope = (reason_code = 'collecting') => ({
  available: false,
  reason_code,
  collection_status: 'collecting',
  collected_issue_count: 751,
  auto_count: 598,
  manual_count: 153,
  evaluated_issue_count: 1,
  observed_at: '2026-11-15T01:06:00+08:00',
});
const metric = (version = 'gen4-release-20261106') => ({
  version_key: version,
  label: version,
  total_cases: 1,
  road_positive_cases: 1,
  sim_positive_cases: 1,
  reproduced_cases: 1,
  sim_repro_rate: 1,
  precision: 1,
  recall: 1,
  f1: 1,
  specificity: 0,
  accuracy: 1,
  positive_auto_repro_rate: 1,
  negative_auto_repro_rate: 0,
  positive_manual_repro_rate: 0,
  evaluated_cases: 1,
  dpe_coverage: 1,
  quality_gate_passed: true,
  root_causes: {},
  source_gt: { total_scenarios: 1, auto_trigger_tp: 1 },
  sim_estimate: {
    estimated_tp: 1,
    estimated_fp: 0,
    estimated_fn: 0,
    same_version_projection: {
      available: true,
      sim_precision: 1,
      sim_business_recall: 1,
    },
  },
});
const summary = (collection) => ({
  business_current_version: 'gen4-release-20261106',
  business_metrics: null,
  business_collection: collection,
  current: metric('gen4-release-20261030'),
  previous: null,
  deltas: {},
  generated_at: '2026-11-15T01:06:00+08:00',
});
const visibleText = (html) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ');

test('overview never renders population-change suppression banner and always displays measured metrics', async () => {
  const collection = scope('population_changed');
  const current = {
    ...metric('gen4-release-20261106'),
    sim_repro_rate: 0.883,
    precision: 0.813,
    recall: 0.779,
    f1: null,
    collection_scope: collection,
  };
  const html = await render(summary(collection), [current]);
  const text = visibleText(html);
  for (const value of ['88.3%', '81.3%', '77.9%', '79.6%']) {
    assert.ok(text.includes(value), `expected ${value} in ${text}`);
  }
  for (const forbidden of ['待补齐最新人口', '完整版本指标暂不展示', '旧冻结结果 Issue']) {
    assert.ok(!text.includes(forbidden), `unexpected ${forbidden} in ${text}`);
  }
  assert.doesNotMatch(html, /colSpan="11"/);
});

test('overview displays covered evaluation_scope metrics and computed F1 even when top-level percentages are null', async () => {
  const collection = {
    ...scope('population_changed'),
    collection_status: 'stable',
  };
  const scoped = {
    ...metric('gen4-release-20261106'),
    sim_repro_rate: null,
    precision: null,
    recall: null,
    f1: null,
    evaluation_scope: {
      complete: true,
      covered: 1252,
      eligible: 1252,
      repro_rate: 0.8834,
      precision: 0.8133,
      recall: 0.7787,
      road_precision: 0.6131,
      road_recall: 0.7852,
    },
    collection_scope: collection,
  };
  const text = visibleText(await render(summary(collection), [scoped], 'en'));
  for (const value of ['88.3%', '81.3%', '77.9%', '79.6%']) {
    assert.ok(text.includes(value), `expected ${value} in ${text}`);
  }
  for (const forbidden of [
    'Latest population awaiting results',
    'Full-version metrics are pending',
    'Prior frozen results',
  ]) {
    assert.ok(!text.includes(forbidden), `unexpected ${forbidden} in ${text}`);
  }
});

test('truly unmeasured release shows minimal pending fallback without collection suppression banner', async () => {
  const collection = scope();
  const unmeasured = {
    ...metric('gen4-release-20261106'),
    sim_repro_rate: null,
    precision: null,
    recall: null,
    f1: null,
    collection_scope: collection,
  };
  const zhText = visibleText(
    await render({ ...summary(collection), current: null }, [unmeasured], 'zh'),
  );
  assert.ok(zhText.includes('待完整仿真'), zhText);
  assert.ok(!zhText.includes('待补齐最新人口'), zhText);
  assert.ok(!zhText.includes('完整版本指标暂不展示'), zhText);

  const enText = visibleText(
    await render({ ...summary(collection), current: null }, [unmeasured], 'en'),
  );
  assert.ok(enText.includes('Awaiting complete simulation'), enText);
  assert.ok(!enText.includes('Full-version metrics are pending'), enText);
});

test('independent ordinary metrics and AutoTriage fallback keep their existing values', async () => {
  const current = metric('gen4-release-20261030');
  current.precision = 0.799;
  const text = visibleText(
    await render(
      {
        ...summary(null),
        business_current_version: current.version_key,
        business_metrics: current,
      },
      [current],
    ),
  );
  assert.ok(text.includes('79.9%'));
  assert.ok(!text.includes('旧冻结结果'));
  const auto = visibleText(
    await render(
      {
        ...summary(scope()),
        business_current_version: null,
        current,
        business_metrics: current,
      },
      [current],
      'en',
      true,
    ),
  );
  assert.ok(auto.includes('79.9%'));
  assert.ok(!auto.includes('Prior frozen-result'));
});

test('historical frozen population retains its measured values and names both populations', async () => {
  const collection = {
    ...scope('population_changed'),
    collection_status: 'stable',
    historical_frozen: true,
    frozen_issue_count: 1500,
    collected_issue_count: 1550,
  };
  const historical = {
    ...metric('gen4-release-20261009'),
    precision: 0.876,
    collection_scope: collection,
  };
  const html = await render(
    summary(scope()),
    [historical, { ...metric(), collection_scope: scope() }],
    'en',
  );
  const text = visibleText(html);
  for (const value of [
    'Historical frozen population',
    'Frozen population 1,500',
    'Currently collected 1,550',
    '87.6%',
  ])
    assert.ok(text.includes(value), value);
  assert.ok(!text.includes('Full-version metrics are pending'));
});

test('stale-retained published release keeps Overview metrics visible with overdue badge', async () => {
  const retained = {
    ...scope('collecting'),
    stale: true,
    collection_completed: true,
    display_retained: true,
    frozen_issue_count: 1625,
    collected_issue_count: 1703,
  };
  const current = {
    ...metric('gen4-release-20261106'),
    precision: 0.814,
    collection_scope: retained,
  };
  const zhText = visibleText(
    await render(
      {
        ...summary(retained),
        business_current_version: current.version_key,
        business_metrics: current,
        business_collection: retained,
      },
      [current],
      'zh',
    ),
  );
  assert.ok(zhText.includes('81.4%'), zhText);
  assert.ok(zhText.includes('采集待更新'), zhText);
  assert.ok(zhText.includes('后台采集更新延迟'), zhText);
  assert.ok(!zhText.includes('完整版本指标暂不展示'), zhText);

  const enText = visibleText(
    await render(
      {
        ...summary(retained),
        business_current_version: current.version_key,
        business_metrics: current,
        business_collection: retained,
      },
      [current],
      'en',
    ),
  );
  assert.ok(enText.includes('81.4%'), enText);
  assert.ok(enText.includes('Collection update overdue'), enText);
  assert.ok(enText.includes('Background collection update is delayed'), enText);
  assert.ok(!enText.includes('Full-version metrics are pending'), enText);
});
