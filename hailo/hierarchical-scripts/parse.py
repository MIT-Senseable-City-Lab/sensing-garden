# import the ClientRunner class from the hailo_sdk_client package
from hailo_sdk_client import ClientRunner

chosen_hw_arch = "hailo8"
# For Hailo-15 devices, use 'hailo15h'
# For Mini PCIe modules or Hailo-8R devices, use 'hailo8r'

onnx_model_name = "london_141-multitask"
onnx_path = "/mnt/f/mit/hailo-resnet-multitask/ptonnx/london_141-multitask.onnx"

runner = ClientRunner(hw_arch=chosen_hw_arch)
hn, npz = runner.translate_onnx_model(
    onnx_path,
    onnx_model_name,
    start_node_names=["input"],
    end_node_names=["family", "genus", "species"],
    net_input_shapes={"input": [1, 3, 224, 224]},
)

hailo_model_har_name = f"{onnx_model_name}_hailo_model.har"
runner.save_har(hailo_model_har_name)
