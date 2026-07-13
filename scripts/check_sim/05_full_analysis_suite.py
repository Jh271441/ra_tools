
import numpy as np
import onnxruntime as ort
import os
import argparse
from tqdm import tqdm

from planning_seed_reader import get_frame, get_tensor_dict, iter_frames

# --- 配置区 ---
EXPECTED_SHAPES = {
    'old_dnn_features': (1, 9800), 'ego_geometric': (1, 1, 10, 5, 2), 'ego_heading': (1, 1, 10, 1),
    'ego_continuous': (1, 1, 10, 3), 'ego_discrete': (1, 1, 10, 1), 'ego_trajectory': (1, 1, 10, 100, 4),
    'ego_valid_geometric': (1, 1, 10), 'ego_valid_history': (1, 1), 'ego_valid_trajectory': (1, 1, 10),
    'agent_geometric': (1, 50, 30, 5, 2), 'agent_heading': (1, 50, 30, 1), 'agent_continuous': (1, 50, 30, 6),
    'agent_discrete': (1, 50, 30, 12), 'agent_trajectory': (1, 50, 30, 50, 4), 'agent_valid_geometric': (1, 50, 30),
    'agent_valid_history': (1, 50), 'agent_valid_trajectory': (1, 50, 30), 'zone_geometric': (1, 10, 1, 32, 2),
    'zone_discrete': (1, 10, 1, 7), 'zone_valid_geometric': (1, 10, 1), 'zone_valid_history': (1, 10),
    'obj_geometric': (1, 20, 1, 10, 2), 'obj_discrete': (1, 20, 1, 1), 'obj_valid_geometric': (1, 20, 1),
    'obj_valid_history': (1, 20), 'tl_continuous': (1, 10, 30, 4), 'tl_discrete': (1, 10, 30, 5),
    'tl_valid_history': (1, 10), 'nearby_lane_geometric': (1, 90, 1, 62, 2), 'nearby_lane_continuous': (1, 90, 1, 2),
    'nearby_lane_discrete': (1, 90, 1, 7), 'nearby_lane_valid_geometric': (1, 90, 1), 'nearby_lane_valid_history': (1, 90)
}

class VoyagerAnalyzer:
    def __init__(self, model_path):
        self.sess = None
        self.model_path = model_path

    def _load_model(self):
        if not self.sess:
            self.sess = ort.InferenceSession(self.model_path, providers=['CPUExecutionProvider'])
        return self.sess

    def msg_to_numpy(self, td_msg):
        if td_msg is None: return {}
        raw_dict = {k: v for k, v in td_msg.items()} if hasattr(td_msg, 'items') else {item.key: item.value for item in td_msg}
        features = {}
        for k, shape in EXPECTED_SHAPES.items():
            if k in raw_dict:
                v = raw_dict[k]
                vals = list(getattr(v, 'float_vals', [])) + list(getattr(v, 'double_vals', [])) + list(getattr(v, 'int_vals', []))
                dtype = np.int32 if any(x in k for x in ["discrete", "valid", "history"]) else np.float32
                try: features[k] = np.array(vals, dtype=dtype).reshape(shape)
                except: features[k] = np.zeros(shape, dtype=dtype)
            else:
                features[k] = np.zeros(shape, dtype=np.int32 if any(x in k for x in ["discrete", "valid", "history"]) else np.float32)
        return features

    def run_inference(self, features):
        sess = self._load_model()
        inputs = {}
        for i in sess.get_inputs():
            name = i.name
            expected_shape = i.shape
            
            if name in features:
                val = features[name]
                # 对齐维度：如果模型期望维度比当前多，尝试在末尾补 1
                if len(val.shape) < len(expected_shape):
                    for _ in range(len(expected_shape) - len(val.shape)):
                        val = np.expand_dims(val, axis=-1)
                
                # 检查并修复由于 reshape 导致的 size 差异
                expected_size = np.prod([s for s in expected_shape if isinstance(s, int)])
                if val.size != expected_size and expected_size > 0:
                     print(f"Warning: {name} size mismatch ({val.size} vs {expected_size}). Padding...")
                     new_val = np.zeros(expected_size, dtype=val.dtype)
                     new_val[:min(val.size, expected_size)] = val.flatten()[:min(val.size, expected_size)]
                     val = new_val.reshape(expected_shape)

                # 转换类型
                if 'int32' in i.type: inputs[name] = val.astype(np.int32)
                elif 'int64' in i.type: inputs[name] = val.astype(np.int64)
                else: inputs[name] = val.astype(np.float32)
        
        try:
            outputs = sess.run(None, inputs)
            return dict(zip([o.name for o in sess.get_outputs()], outputs))
        except Exception as e:
            print(f"Inference failed: {e}")
            # 如果推理失败，打印输入详情供调试
            for k, v in inputs.items():
                print(f"  Input '{k}': shape={v.shape}, dtype={v.dtype}")
            raise e

    def analyze_single_frame(
        self, road_path, sim_path, target_ms, offset, road_output, sim_output
    ):
        print(f"\n[1] Analyzing Specific Frame ({offset:+d} offset from {target_ms}ms)")
        road_frame = get_frame(road_path, target_ms, offset=offset)
        sim_frame = get_frame(sim_path, target_ms, offset=offset)
        if road_frame is None or sim_frame is None:
            raise RuntimeError("Could not find the requested frame in both bags")
        road_tensor_dict = get_tensor_dict(road_frame.message)
        sim_tensor_dict = get_tensor_dict(sim_frame.message)
        if not road_tensor_dict or not sim_tensor_dict:
            raise RuntimeError("TensorDict is empty in one or both selected frames")
        feat_r = self.msg_to_numpy(road_tensor_dict)
        feat_s = self.msg_to_numpy(sim_tensor_dict)
        print(f"road frame: {road_frame.time_s:.6f}")
        print(f"sim frame : {sim_frame.time_s:.6f}")

        print("\nSignificant Input Differences (>0.01):")
        for k in sorted(feat_r.keys()):
            diff = np.max(np.abs(feat_r[k].astype(float) - feat_s[k].astype(float)))
            if diff > 0.01: print(f"  {k:<30} | Max Diff: {diff:.4f}")

        print("\n[2] Running Inference for this frame...")
        out_r, out_s = self.run_inference(feat_r), self.run_inference(feat_s)
        print(f"{'Output Name':<30} | {'Road Val':<15} | {'Sim Val':<15} | {'Diff':<10}")
        for k in out_r.keys():
            v_r, v_s = out_r[k].flatten()[0], out_s[k].flatten()[0]
            print(f"{k:<30} | {v_r:<15.4f} | {v_s:<15.4f} | {abs(v_r-v_s):<10.4f}")

        print("\n[3] Exporting NPZ files...")
        np.savez(road_output, **feat_r)
        np.savez(sim_output, **feat_s)
        print(f"Saved {road_output} and {sim_output}")

    def process_full_bag(self, road_path, sim_path):
        print(f"\n[4] Full Bag Inference Comparison")
        def get_inference_series(path):
            outputs = []
            for frame in tqdm(iter_frames(path), desc=f"Inference {os.path.basename(path)}"):
                tensor_dict = get_tensor_dict(frame.message)
                if not tensor_dict:
                    outputs.append(None)
                    continue
                feat = self.msg_to_numpy(tensor_dict)
                outputs.append(self.run_inference(feat))
            return outputs

        road_out = get_inference_series(road_path)
        sim_out = get_inference_series(sim_path)
        
        print("\nFull Sequence Summary (stuck_score):")
        for i in range(min(len(road_out), len(sim_out))):
            r, s = road_out[i], sim_out[i]
            if r and s:
                print(f"Frame {i}: Road={r['stuck_score'][0][0]:.4f}, Sim={s['stuck_score'][0][0]:.4f}, Diff={abs(r['stuck_score']-s['stuck_score'])[0][0]:.4f}")
            elif not r and not s: pass
            else: print(f"Frame {i}: Mismatch (One side is empty)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--road", default="road.bag")
    parser.add_argument("--sim", default="sim.bag")
    parser.add_argument("--ts", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--offset", type=int, default=-1)
    parser.add_argument("--road-output", default="road_frame.npz")
    parser.add_argument("--sim-output", default="sim_frame.npz")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    analyzer = VoyagerAnalyzer(args.model)
    analyzer.analyze_single_frame(
        args.road,
        args.sim,
        args.ts,
        args.offset,
        args.road_output,
        args.sim_output,
    )
    if args.full: analyzer.process_full_bag(args.road, args.sim)
