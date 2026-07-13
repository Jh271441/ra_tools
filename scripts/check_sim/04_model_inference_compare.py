
import argparse
import onnxruntime as ort
import numpy as np
import os
import onnx
from onnx import helper


def _patched_model_path(model_path):
    base = os.path.basename(model_path)
    root, ext = os.path.splitext(base)
    return os.path.join(os.getcwd(), f"{root}.ort_compat{ext}")


def ensure_ort_compatible_model(model_path):
    patched_path = _patched_model_path(model_path)
    model = onnx.load(model_path)
    initializers = {item.name: item for item in model.graph.initializer}
    replaced = 0
    rewritten_nodes = []
    zero_name = "__ort_compat_zero_f32"

    if zero_name not in initializers:
        model.graph.initializer.append(
            helper.make_tensor(zero_name, onnx.TensorProto.FLOAT, [1], [0.0])
        )
        initializers = {item.name: item for item in model.graph.initializer}

    for node in model.graph.node:
        if node.op_type == "LayerNormalization" and "gbm_feature_encoder" in node.name:
            bias = initializers.get(node.input[2])
            if bias is not None and tuple(bias.dims) == (1,):
                zeroed_name = f"{node.output[0]}__zeroed"
                rewritten_nodes.append(
                    helper.make_node(
                        "Mul",
                        [node.input[0], zero_name],
                        [zeroed_name],
                        name=f"{node.name}/ort_compat_zero",
                    )
                )
                rewritten_nodes.append(
                    helper.make_node(
                        "Add",
                        [zeroed_name, node.input[2]],
                        list(node.output),
                        name=f"{node.name}/ort_compat_bias",
                    )
                )
                replaced += 1
                continue
        rewritten_nodes.append(node)

    if replaced == 0:
        return model_path

    del model.graph.node[:]
    model.graph.node.extend(rewritten_nodes)
    onnx.save(model, patched_path)
    print(f"Created ONNX Runtime compatible model: {patched_path} ({replaced} scalar LayerNorm nodes rewritten)")
    return patched_path

def run_inference(model_path, data_path):
    model_path = ensure_ort_compatible_model(model_path)
    sess = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    data = np.load(data_path)
    
    # Map inputs and cast to correct type
    inputs = {}
    for i in sess.get_inputs():
        name = i.name
        expected_type = i.type
        
        if name in data:
            val = data[name]
            # Map onnx types to numpy types
            if 'int32' in expected_type:
                val = val.astype(np.int32)
            elif 'float' in expected_type:
                val = val.astype(np.float32)
            elif 'int64' in expected_type:
                val = val.astype(np.int64)
            
            inputs[name] = val
        else:
            print(f"Warning: Input '{name}' not found in {data_path}")
            
    outputs = sess.run(None, inputs)
    output_names = [o.name for o in sess.get_outputs()]
    return dict(zip(output_names, outputs))

def main():
    parser = argparse.ArgumentParser(description="Compare ONNX outputs for road and sim NPZ inputs")
    parser.add_argument("--model", required=True)
    parser.add_argument("--road", default="road_features.npz")
    parser.add_argument("--sim", default="sim_features.npz")
    args = parser.parse_args()

    model_path = args.model
    road_data = args.road
    sim_data = args.sim
    
    print(f"Running inference on {road_data}...")
    res_road = run_inference(model_path, road_data)
    
    print(f"Running inference on {sim_data}...")
    res_sim = run_inference(model_path, sim_data)
    
    print("\n--- Model Output Comparison ---")
    for k in res_road.keys():
        v_road = res_road[k]
        v_sim = res_sim[k]
        
        diff = np.max(np.abs(v_road - v_sim))
        print(f"Output: {k}")
        print(f"  Shape: {v_road.shape}")
        print(f"  Max Abs Diff: {diff:.6f}")
        
        if diff > 0.001:
            print(f"  Road output sample: {v_road.flatten()[:5]}")
            print(f"  Sim  output sample: {v_sim.flatten()[:5]}")
        else:
            print("  Outputs are practically IDENTICAL.")
        print("-" * 30)

if __name__ == "__main__":
    main()
