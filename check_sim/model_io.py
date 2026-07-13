"""Shared ONNX helpers for the check_sim inference scripts (04, 05, 07).

`ensure_ort_compatible_model` rewrites the scalar LayerNormalization bias nodes
that older ONNX Runtime builds reject. Numbered entrypoints depend on this
module instead of importing one another.
"""

import os


def _patched_model_path(model_path):
    base = os.path.basename(model_path)
    root, ext = os.path.splitext(base)
    return os.path.join(os.getcwd(), f"{root}.ort_compat{ext}")


def ensure_ort_compatible_model(model_path):
    import onnx
    from onnx import helper

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
    print(
        f"Created ONNX Runtime compatible model: {patched_path} "
        f"({replaced} scalar LayerNorm nodes rewritten)"
    )
    return patched_path


def create_session(model_path, intra_op_threads=4):
    import onnxruntime as ort

    patched_model = ensure_ort_compatible_model(model_path)
    options = ort.SessionOptions()
    options.intra_op_num_threads = intra_op_threads
    options.inter_op_num_threads = 1
    return ort.InferenceSession(
        patched_model,
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )


def cast_for_input(array, input_type):
    import numpy as np

    if "int32" in input_type:
        return array.astype(np.int32)
    if "int64" in input_type:
        return array.astype(np.int64)
    return array.astype(np.float32)


def run_inference(session, features):
    missing = [item.name for item in session.get_inputs() if item.name not in features]
    if missing:
        raise KeyError(f"Missing model inputs: {', '.join(missing)}")

    feed = {
        item.name: cast_for_input(features[item.name], item.type)
        for item in session.get_inputs()
    }
    values = session.run(None, feed)
    return {
        output.name: value for output, value in zip(session.get_outputs(), values)
    }
