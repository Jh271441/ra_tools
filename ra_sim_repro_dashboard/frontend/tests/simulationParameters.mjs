import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { buildSimulationParameters, SIM_EXTRA_ARGS, ANIMATION_CONFIG } from '../src/lib/simulationParameters.ts';

const input = { binaryId: '1810741', sourceKind: 'ids', source: '40064248:0, 40064242:0，40064248:0', animation: false, concurrency: '3000' };
test('blank form still exposes full baseline templates without inventing a binary or scenario', () => {
  const generated = buildSimulationParameters({ ...input, binaryId: '', source: '' });
  const preview = JSON.parse(generated.singleJobJsonPreview);
  assert.equal(preview.common_params.binary_id, null);
  assert.deepEqual(preview.generator_params.ids, []);
  assert.deepEqual(preview.sim_common_params.override_enabled_modules, ['PLANNING']);
  assert.equal(preview.sim_common_params.sim_extra_args, SIM_EXTRA_ARGS);
  assert.deepEqual(JSON.parse(generated.jobJsonPreview), [preview]);
  assert.match(generated.jobArgsPreview, /<SCENARIO_ID>/);
  assert.match(generated.jobArgsPreview, /--planning_enable_warmup_frame_state/);
  assert.equal(generated.jobJson, '');
});
test('single-file and batch import use different root shapes with identical job settings', () => {
  const generated = buildSimulationParameters(input);
  const single = JSON.parse(generated.singleJobJson);
  const batch = JSON.parse(generated.jobJson);
  assert.equal(Array.isArray(single), false);
  assert.ok(Array.isArray(single.common_params.job_labels));
  assert.ok(Array.isArray(batch));
  assert.deepEqual(batch, [single]);
  assert.equal(buildSimulationParameters({ ...input, binaryId: '' }).singleJobJson, '');
});
function split(value) {
  const result = spawnSync('python3', ['-c', 'import sys,shlex,json;print(json.dumps(shlex.split(sys.stdin.read())))'], { input: value, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}
test('native Orion import uses one explicit binary and deduplicated scenarios, not a stale default label', () => {
  const generated = buildSimulationParameters(input);
  const [job] = JSON.parse(generated.jobJson);
  assert.deepEqual(job.generator_params, { input_type: 'ids', approved_scenarios_only: false, ids: ['40064248:0', '40064242:0'], labels: [], scenario_sets: [], labels_not: [], scenario_tags: [] });
  assert.equal(job.common_params.binary_id, 1810741);
  assert.equal(job.common_params.launch_mode, 'binary');
  assert.equal(job.launch_job_params.max_concurrency, 3000);
  assert.equal(job.launch_job_params.cluster, 'prod_gen4');
  assert.equal(job.launch_job_params.priority, 'high');
  assert.equal(job.sim_common_params.upload_output_bag, 'always');
  assert.deepEqual(job.sim_common_params.override_enabled_modules, ['PLANNING']);
  assert.equal(job.sim_common_params.use_dpe, true);
  assert.equal(job.common_params.upload_retention_days, 7);
});
test('Job and Sim Plan shell strings preserve the complete simulator payload and nested animation JSON', () => {
  const generated = buildSimulationParameters({ ...input, animation: true });
  for (const value of [generated.jobArgs, generated.simPlanArgs]) {
    const tokens = split(value);
    assert.equal(tokens[tokens.indexOf('--sim-extra-args') + 1], SIM_EXTRA_ARGS);
    assert.equal(tokens[tokens.indexOf('--ares-animation-config') + 1], ANIMATION_CONFIG);
    assert.equal(tokens[tokens.indexOf('--simulator-cache') + 1], 'disabled');
    assert.equal(tokens[tokens.indexOf('--override-enabled-modules') + 1], 'PLANNING');
    assert.ok(tokens.includes('--create-animation'));
    assert.equal(tokens[tokens.indexOf('--upload-output-bag') + 1], 'always');
    assert.equal(tokens[tokens.indexOf('--upload-retention-days') + 1], '7');
  }
  assert.ok(!split(generated.simPlanArgs).includes('--binary-id'));
  assert.equal(JSON.parse(generated.jobJson)[0].sim_common_params.sim_extra_args, SIM_EXTRA_ARGS);
  assert.equal(JSON.parse(generated.singleJobJson).sim_common_params.animation_config, '');
  const extraTokens = split(JSON.parse(generated.singleJobJson).common_params.extra_args);
  assert.equal(extraTokens[extraTokens.indexOf('--ares-animation-config') + 1], ANIMATION_CONFIG);
});
test('quoted labels stay a single argument and cannot add flags or shell substitutions', () => {
  const source = "test's $(echo nope) `echo nope` ; --override-enabled-modules ROUTING";
  const generated = buildSimulationParameters({ ...input, sourceKind: 'label', source });
  const tokens = split(generated.jobArgs);
  assert.equal(tokens[tokens.indexOf('--labels') + 1], source);
  assert.equal(tokens.filter(t => t === '--override-enabled-modules').length, 1);
  assert.deepEqual(JSON.parse(generated.jobJson)[0].generator_params.labels, [source]);
});
test('invalid identities or concurrency cannot produce a launchable Job; generic Sim Plan remains available', () => {
  for (const patch of [{ binaryId: '' }, { binaryId: '0' }, { source: '' }, { source: '40064248 --foo' }, { concurrency: '0' }, { concurrency: '3001' }, { concurrency: '1.5' }]) {
    const generated = buildSimulationParameters({ ...input, ...patch });
    assert.ok(generated.errors.length);
    assert.equal(generated.jobJson, '');
    assert.equal(generated.jobArgs, '');
    assert.ok(generated.simPlanArgs.includes('--sim-extra-args'));
  }
});
test('baseline adds neither VLM nor experimental replay or animation unless requested', () => {
  const generated = buildSimulationParameters(input);
  assert.doesNotMatch(generated.simPlanArgs, /vlm|sim_state_recovery_level|independent_replay|reencode-h265|--create-animation/);
  assert.equal(JSON.parse(generated.jobJson)[0].sim_common_params.create_animation, false);
  const extraTokens = split(JSON.parse(generated.singleJobJson).common_params.extra_args);
  assert.equal(extraTokens[extraTokens.indexOf('--ares-animation-config') + 1], ANIMATION_CONFIG);
});
