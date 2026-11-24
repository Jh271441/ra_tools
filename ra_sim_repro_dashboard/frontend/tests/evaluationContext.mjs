import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  comparisonParams,
  changeEvaluationRelease,
  changeEvaluationReleaseQuery,
  collectionIssuesQuery,
  validEvaluationDates,
  comparisonRevisions,
} from '../src/lib/evaluationContext.ts';

const selected = {
  release: 'gen4-release-20261016',
  profile_id: 'auto_triage_sql_v2',
  date_start: '2026-09-19',
  date_end: '2026-10-28',
};

test('a saved 10-16 date range does not remove later releases from the comparison', () => {
  const saved = [
    { release: 'gen4-release-20261016', start: '2026-09-19', end: '2026-10-28' },
    { release: 'gen4-release-20261023', start: '2026-10-29', end: '2026-11-04' },
  ];
  const query = comparisonParams(selected);
  const comparison = saved.filter(
    (scope) => !query.has('date_end') || scope.start <= query.get('date_end'),
  );
  assert.deepEqual(
    comparison.map((scope) => scope.release),
    ['gen4-release-20261016', 'gen4-release-20261023'],
  );
  assert.equal(query.get('profile_id'), selected.profile_id);
  assert.equal(query.has('release'), false);
  assert.equal(query.has('date_start'), false);
  assert.equal(selected.date_end, '2026-10-28');
});

test('changing release loads its saved scope while keeping the evaluation rules', () => {
  const next = changeEvaluationRelease(selected, 'gen4-release-20261023');
  assert.deepEqual(next, {
    release: 'gen4-release-20261023',
    profile_id: selected.profile_id,
    date_start: undefined,
    date_end: undefined,
  });
  assert.equal({ ...selected, ...next }.date_start, undefined);
  assert.equal({ ...selected, ...next }.date_end, undefined);
  assert.equal(validEvaluationDates(next), true);
  assert.equal(changeEvaluationRelease(selected, selected.release), selected);
});

test('explicit historical dates still require a complete ordered pair', () => {
  assert.equal(validEvaluationDates(selected), true);
  assert.equal(validEvaluationDates({ ...selected, date_start: undefined }), false);
  assert.equal(validEvaluationDates({ ...selected, date_start: '2026-10-29' }), false);
});

test('Issue and simulation version navigation clears only the old sample dates and page', () => {
  const before = new URLSearchParams({
    release: selected.release,
    version: selected.release,
    date_start: selected.date_start,
    date_end: selected.date_end,
    profile: selected.profile_id,
    basis: 'auto-triage',
    page: '4',
    page_size: '50',
    release_start: '2026-09-09',
  });
  const next = changeEvaluationReleaseQuery(before, 'gen4-release-20261023');
  assert.equal(next.get('date_start'), null);
  assert.equal(next.get('date_end'), null);
  assert.equal(next.get('release'), 'gen4-release-20261023');
  assert.equal(next.get('version'), 'gen4-release-20261023');
  assert.equal(next.get('page'), '1');
  assert.equal(next.get('page_size'), '50');
  assert.equal(next.get('profile'), selected.profile_id);
  assert.equal(next.get('release_start'), '2026-09-09');
  assert.equal(
    changeEvaluationReleaseQuery(before, selected.release).get('date_start'),
    selected.date_start,
  );
  assert.equal(before.get('page'), '4');
  const current = changeEvaluationReleaseQuery(before, '@current');
  assert.equal(current.get('release'), null);
  assert.equal(current.get('version'), null);
  assert.equal(current.get('date_end'), null);
});

test('an explicitly selected historical scope uses the same revision in its cards and curve', () => {
  const current16 = { context: selected, revision_key: 'latest-16' };
  const current23 = { context: { release: 'gen4-release-20261023' }, revision_key: 'latest-23' };
  const history16 = {
    context: { ...selected, date_start: '2026-10-01' },
    revision_key: 'historical-16',
  };
  const result = comparisonRevisions([current16, current23], history16);
  assert.deepEqual(
    result.map((value) => value.revision_key),
    ['historical-16', 'latest-23'],
  );
  assert.equal(current16.revision_key, 'latest-16');
  assert.equal(comparisonRevisions([current23], history16).length, 2);
});

test('collection drill-down identifies the whole road population and survives URL reload', () => {
  const before = new URLSearchParams({
    release: 'gen4-release-20261106',
    version: 'gen4-release-20261106',
    issue_view: 'simulation',
    page: '5',
    page_size: '50',
    query: 'cn-old',
    label: 'old-scene',
    issue: 'cn-old',
    scenario: 's-old',
    root_cause: 'FN',
    precision_label: 'FN',
    coverage: 'missing',
    changed: '1',
    basis: 'auto-triage',
    date_start: '2026-11-09',
    date_end: '2026-11-09',
    profile: 'auto_triage_review_v1',
    release_start: '2026-09-12',
    release_end: '2026-11-12',
  });
  const query = collectionIssuesQuery(before, 'gen4-release-20261106');
  const reloaded = new URL('https://dashboard.test/sim/issues?' + query).searchParams;
  assert.equal(reloaded.get('issue_view'), 'collection');
  assert.equal(reloaded.get('page'), '1');
  assert.equal(reloaded.get('page_size'), '50');
  assert.equal(reloaded.get('release'), 'gen4-release-20261106');
  assert.equal(reloaded.get('version'), 'gen4-release-20261106');
  for (const key of [
    'query',
    'label',
    'issue',
    'scenario',
    'root_cause',
    'precision_label',
    'coverage',
    'changed',
    'basis',
    'date_start',
    'date_end',
  ])
    assert.equal(reloaded.has(key), false, key);
  assert.equal(reloaded.get('profile'), 'auto_triage_review_v1');
  assert.equal(reloaded.get('release_start'), '2026-09-12');
  assert.equal(reloaded.get('release_end'), '2026-11-12');
  assert.equal(
    before.get('issue_view'),
    'simulation',
    'the old route is retained for browser Back',
  );
  assert.equal(before.get('query'), 'cn-old');
});

test('collection drill-down targets the clicked pending release without changing evaluation navigation', () => {
  const before = new URLSearchParams({
    release: 'gen4-release-20261030',
    version: 'gen4-release-20261030',
    page: '9',
    page_size: '100',
    query: 'stale',
  });
  const collection = collectionIssuesQuery(before, 'gen4-release-20261106');
  assert.equal(collection.get('release'), 'gen4-release-20261106');
  assert.equal(collection.get('issue_view'), 'collection');
  assert.equal(collection.get('page'), '1');
  const evaluation = changeEvaluationReleaseQuery(before, 'gen4-release-20261106');
  assert.equal(evaluation.has('issue_view'), false);
  assert.equal(evaluation.get('query'), 'stale', 'existing evaluation route behavior is unchanged');
});
