// Verified against all task arguments in Job 47739079 (2026-10-19).
// Simulation flags retain the baseline; output and scheduling are user template defaults.
export const ORION_LAUNCH_URL = 'https://voyager.intra.xiaojukeji.com/static/management/#/orion/launch';
export const BASELINE_JOB_URL = 'https://voyager.intra.xiaojukeji.com/static/management/#/orion/job/detail?job_id=47739079';

export const SIM_FLAGS = [
  ['--sim_disable_loading_assist_topic', '不加载路测 assist topic，重新计算仿真触发。'],
  ['--sim_aligned_mode', '启用 aligned 仿真模式。'],
  ['--planning_use_old_stuck_feature_extractor_length_only_in_sim', '沿用基线的卡顿特征历史长度兼容设置。'],
  ['--planning_enable_warmup_frame_state', '启用 warmup 帧状态。'],
  ['--planning_enable_warmup_frame_seed', '启用 warmup 帧 seed。'],
  ['--planning_enable_sim_planner_init_state_recovery_mode', '恢复 planner 初始状态。'],
  ['--sim_smart_agent', '启用 smart agent。'],
  ['--sim_smart_agent_config_file SIM_dl_agent_second_order_model.conf', '使用基线的二阶 smart-agent 模型。'],
  ['--sim_override_smart_agent_config {ego_pose_divergence_threshold:1.5,ego_heading_divergence_threshold:8}', '位置 / 航向发散阈值使用 1.5 / 8。'],
] as const;

export const SIM_EXTRA_ARGS = SIM_FLAGS.map(([flag]) => flag).join(' ');
export const ANIMATION_CONFIG = JSON.stringify({ layout: 'RA_AutoTrigger_Animation_Panel' });

export function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}

export interface ParameterInput {
  binaryId: string;
  sourceKind: 'ids' | 'label';
  source: string;
  animation: boolean;
  concurrency: string;
}

export function buildSimulationParameters(input: ParameterInput) {
  const errors: string[] = [];
  const binary = input.binaryId.trim();
  const source = input.source.trim();
  const validBinary = /^[1-9]\d*$/.test(binary) && Number.isSafeInteger(Number(binary));
  if (!validBinary) errors.push(binary ? 'Binary ID 无效' : '待填 Binary ID');
  const ids = [...new Set(source.split(/[\s,，]+/).filter(Boolean))];
  const validSource = input.sourceKind === 'ids'
    ? ids.length > 0 && ids.every(id => /^[1-9]\d*(?::\d+)?$/.test(id))
    : !!source && !/[\r\n\u0000]/.test(source);
  if (!validSource) errors.push(source ? '场景格式无效' : '待填场景');
  const concurrency = Number(input.concurrency);
  const validConcurrency = /^\d+$/.test(input.concurrency) && Number.isInteger(concurrency) && concurrency >= 1 && concurrency <= 3000;
  if (!validConcurrency) errors.push('并发需为 1–3000');

  const common = [
    '--override-enabled-modules PLANNING',
    '--use-trip-hdmap',
    '--use-dpe 1',
    '--use-deepnet-cache 1',
    '--use-remote-serving 1',
    '--simulator-cache disabled',
    '--enable-log-event',
    '--enable-stats',
    '--upload-output-bag always',
    '--upload-retention-days 7',
    '--routing-constraint-endpoint default',
    '--animation-type ares_studio',
    ...(input.animation ? ['--create-animation', `--ares-animation-config ${shellQuote(ANIMATION_CONFIG)}`] : []),
    `--sim-extra-args ${shellQuote(SIM_EXTRA_ARGS)}`,
  ];
  const simPlanArgs = common.join(' ');
  const sourceArgument = input.sourceKind === 'ids' ? `-i ${ids.join(' ')}` : `--labels ${shellQuote(source)}`;
  const jobArgs = errors.length ? '' : [`--binary-id ${binary}`, '--region cn', sourceArgument, ...common].join(' ');
  const previewSource = validSource ? sourceArgument : input.sourceKind === 'ids' ? `-i ${shellQuote('<SCENARIO_ID>')}` : `--labels ${shellQuote('<SCENARIO_LABEL>')}`;
  const jobArgsPreview = [`--binary-id ${validBinary ? binary : shellQuote('<BINARY_ID>')}`, '--region cn', previewSource, ...common].join(' ');
  // Native Orion launch-page batch export schema, observed 2026-10-19.
  const jobJsonPreview = JSON.stringify([{
    common_params: {
      job_labels: [], region: 'CN', has_binary: true, launch_mode: 'binary', require_binary: true,
      extra_args: [
        '--use-trip-hdmap', '--simulator-cache disabled', '--routing-constraint-endpoint default',
        '--animation-type ares_studio',
        `--ares-animation-config ${shellQuote(ANIMATION_CONFIG)}`,
      ].join(' '),
      use_lkgr_binary: false, enable_stats: true, enable_log_event: true,
      upload_retention_days: 7, binary_id: validBinary ? Number(binary) : null,
    },
    launch_job_params: { priority: 'high', cluster: 'prod_gen4', max_concurrency: validConcurrency ? concurrency : null },
    sim_common_params: {
      upload_output_bag: 'always', use_deepnet_cache: true, use_remote_serving: true,
      use_dpe: true, override_enabled_modules: ['PLANNING'],
      sim_extra_args: SIM_EXTRA_ARGS, create_animation: input.animation,
      ignore_animation_failure: false,
      animation_config: '',
      dpe_config: '', evaluation_binary_id: null,
    },
    generator_params: {
      input_type: input.sourceKind === 'ids' ? 'ids' : 'labels', approved_scenarios_only: false,
      ...(input.sourceKind === 'ids' ? { ids: validSource ? ids : [], labels: [] } : { labels: validSource ? [source] : [], ids: [] }),
      scenario_sets: [], labels_not: [], scenario_tags: [],
    },
  }], null, 2);
  // Orion's “从文件导入” accepts an object; “批量导入” accepts an array.
  // Passing the array to the single-job importer crashes its job_labels field.
  const singleJobJsonPreview = JSON.stringify(JSON.parse(jobJsonPreview)[0], null, 2);
  const jobJson = errors.length ? '' : jobJsonPreview;
  const singleJobJson = errors.length ? '' : singleJobJsonPreview;
  return { errors, jobArgs, jobArgsPreview, jobJson, jobJsonPreview, singleJobJson, singleJobJsonPreview, simPlanArgs, concurrency, sourceArgument };
}
