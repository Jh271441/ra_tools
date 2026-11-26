#include <ifx/ifx.h>

#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

thread_local std::string last_error;

std::vector<int32_t> dimensions(const ifx::IONode& node) {
  switch (node.sDataFormat) {
    case ifx::TENSOR_FORMAT_W: return {node.sW};
    case ifx::TENSOR_FORMAT_NW: return {node.sN, node.sW};
    case ifx::TENSOR_FORMAT_OI: return {node.sO, node.sI};
    case ifx::TENSOR_FORMAT_HW: return {node.sH, node.sW};
    case ifx::TENSOR_FORMAT_NC: return {node.sN, node.sC};
    case ifx::TENSOR_FORMAT_NHW: return {node.sN, node.sH, node.sW};
    case ifx::TENSOR_FORMAT_CHW: return {node.sC, node.sH, node.sW};
    case ifx::TENSOR_FORMAT_NCHW: return {node.sN, node.sC, node.sH, node.sW};
    case ifx::TENSOR_FORMAT_NHWC: return {node.sN, node.sH, node.sW, node.sC};
    case ifx::TENSOR_FORMAT_NCDHW: return {node.sN, node.sC, node.sD, node.sH, node.sW};
    default: throw std::runtime_error("Unexpected IFX tensor format for " + node.sBlobName);
  }
}

const char* dtype_name(ifx::DataType dt) {
  switch (dt) {
    case ifx::DATA_TYPE_FP32: return "float32";
    case ifx::DATA_TYPE_INT32: return "int32";
    case ifx::DATA_TYPE_FP16: return "float16";
    case ifx::DATA_TYPE_INT8: return "int8";
    default: return "unknown";
  }
}

struct TensorDeleter {
  void operator()(ifx::Tensor* tensor) const {
    if (tensor) tensor->destroy();
  }
};

struct Model {
  std::unique_ptr<ifx::Graph> graph;
  ifx::Session* session = nullptr;
  std::vector<ifx::IONode> inputs;
  std::vector<ifx::IONode> outputs;
  std::map<std::string, ifx::Tensor*> output_buffers;

  ~Model() {
    for (auto& [name, tensor] : output_buffers) TensorDeleter{}(tensor);
  }
};

const std::vector<ifx::IONode>& nodes(Model* model, int output) {
  return output ? model->outputs : model->inputs;
}

}  // namespace

extern "C" const char* ifx_validation_error() {
  return last_error.c_str();
}

extern "C" Model* ifx_validation_open(const char* path, int cuda) {
  try {
    ifx::GraphOptions options;
    options.sDeviceType = cuda ? ifx::DEVICE_TYPE_CUDA : ifx::DEVICE_TYPE_X86;
    options.sDeviceId = 0;
    options.sNumThreads = 2;
    options.sEnableHalf = cuda != 0;
    auto model = std::make_unique<Model>();
    model->graph.reset(ifx::Graph::create(options));
    if (!model->graph) throw std::runtime_error("Graph::create returned null");
    const int status = model->graph->loadIfxEncryptModel(path, &model->inputs, &model->outputs);
    if (status != 0) throw std::runtime_error("loadIfxEncryptModel code " + std::to_string(status));
    model->session = model->graph->createSession();
    if (!model->session) throw std::runtime_error("Graph::createSession returned null");
    for (const auto& node : model->outputs) {
      model->output_buffers.emplace(node.sBlobName, ifx::Tensor::create());
    }
    return model.release();
  } catch (const std::exception& error) {
    last_error = error.what();
    return nullptr;
  } catch (...) {
    last_error = "Unknown IFX model load error";
    return nullptr;
  }
}

extern "C" void ifx_validation_close(Model* model) {
  delete model;
}

extern "C" int ifx_validation_count(Model* model, int output) {
  return static_cast<int>(nodes(model, output).size());
}

extern "C" const char* ifx_validation_name(Model* model, int output, int index) {
  return nodes(model, output).at(index).sBlobName.c_str();
}

extern "C" const char* ifx_validation_dtype_name(Model* model, int output, int index) {
  return dtype_name(nodes(model, output).at(index).sDataType);
}

extern "C" int ifx_validation_shape(Model* model, int output, int index, int32_t* shape, int* dtype) {
  try {
    const auto& node = nodes(model, output).at(index);
    const auto dims = dimensions(node);
    std::memcpy(shape, dims.data(), dims.size() * sizeof(int32_t));
    *dtype = static_cast<int>(node.sDataType);
    return static_cast<int>(dims.size());
  } catch (const std::exception& error) {
    last_error = error.what();
    return -1;
  }
}

extern "C" int ifx_validation_infer(Model* model, void** data) {
  try {
    std::map<std::string, ifx::Tensor*> input_map;
    std::vector<std::unique_ptr<ifx::Tensor, TensorDeleter>> input_storage;
    const ifx::DeviceInfo host{ifx::DEVICE_TYPE_X86, 0};
    for (size_t i = 0; i < model->inputs.size(); ++i) {
      const auto& node = model->inputs[i];
      auto dims = dimensions(node);
      if (!dims.empty() && dims[0] <= 0) dims[0] = 1;
      auto* input = ifx::Tensor::create(host, dims, node.sDataFormat,
                                        node.sDataType, data[i], model->session->getDevice());
      if (!input) throw std::runtime_error("Tensor::create returned null for " + node.sBlobName);
      input_storage.emplace_back(input);
      input_map.emplace(node.sBlobName, input);
    }
    const int status = model->session->doInference(&input_map, &model->output_buffers);
    if (status != 0) throw std::runtime_error("doInference code " + std::to_string(status));
    return 0;
  } catch (const std::exception& error) {
    last_error = error.what();
    return -1;
  } catch (...) {
    last_error = "Unknown IFX inference error";
    return -1;
  }
}

extern "C" const float* ifx_validation_output_fp32(Model* model, int index, int* num_floats) {
  try {
    const auto& node = model->outputs.at(index);
    auto* output = model->output_buffers.at(node.sBlobName);
    if (!output || output->getDataType() != ifx::DATA_TYPE_FP32) {
      throw std::runtime_error("Non-FP32 or null output tensor for " + node.sBlobName);
    }
    const int bytes = output->getByteSize();
    if (bytes <= 0 || (bytes % static_cast<int>(sizeof(float))) != 0) {
      throw std::runtime_error("Invalid byte size for output " + node.sBlobName);
    }
    const auto* host_ptr = static_cast<const float*>(output->host());
    if (!host_ptr) throw std::runtime_error("Null host pointer for output " + node.sBlobName);
    *num_floats = bytes / static_cast<int>(sizeof(float));
    return host_ptr;
  } catch (const std::exception& error) {
    last_error = error.what();
    return nullptr;
  } catch (...) {
    last_error = "Unknown IFX output read error";
    return nullptr;
  }
}
