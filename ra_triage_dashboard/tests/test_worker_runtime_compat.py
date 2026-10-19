import hashlib
import unittest
from types import SimpleNamespace
from ra_triage_dashboard.app.batch_prediction_worker import apply_prediction_configuration, safe_experiment_config
from ra_triage_dashboard.app.prompt_catalog import DEFAULT_FRAME_OFFSETS_MS


class WorkerRuntimeCompatibilityTest(unittest.TestCase):
    def test_inspect_supports_runtime_without_removed_options_field(self):
        experiment = SimpleNamespace(model_name='test', prompt_version='test',
            prompt_template='test', config_merge_mode='none', frame_offsets_ms=[0],
            gateway_window_ms=[-1, 1], pose_yielding_window_ms=[-1, 1],
            time_window_offsets_ms=None, camera_topic='/camera', camera_topics=['/camera'],
            use_ra_event=True, use_bev_animation=False, bev_mode='disabled',
            bev_frame_offsets_ms=[], max_tokens=512, temperature=0.6, top_p=0.8, top_k=50)
        self.assertFalse(safe_experiment_config(experiment, 'default')['use_ra_options'])

    def test_unsupported_options_cannot_be_silently_ignored(self):
        prompt = '根据输入的相机图像和 RA Events，严格输出三分类结果：误触发、正确触发、无需协助，并解释判定理由。'
        request = dict(prompt_version='test', prompt_template=prompt,
            prompt_template_sha256=hashlib.sha256(prompt.encode()).hexdigest(), prompt_mode='custom',
            input_profile='camera_ra_options', input_config=dict(profile_id='camera_ra_options',
                frame_offsets_ms=list(DEFAULT_FRAME_OFFSETS_MS), use_ra_event=True, use_ra_options=True,
                use_trajectory_summary=False, use_ares_capture=False, use_bev_animation=False))
        with self.assertRaisesRegex(ValueError, '不支持 RA/SWAG Options'):
            apply_prediction_configuration(SimpleNamespace(), request)
        supported = SimpleNamespace(use_ra_options=False)
        apply_prediction_configuration(supported, request)
        self.assertTrue(supported.use_ra_options)
