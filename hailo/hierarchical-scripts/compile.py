from hailo_sdk_client import ClientRunner

model_name = "london_141-multitask"
quantized_model_har_path = f"/mnt/f/mit/hailo-resnet-multitask/optimise/{model_name}_quantized_model.har"

runner = ClientRunner(har=quantized_model_har_path)
hef = runner.compile()

file_name = f"/mnt/f/mit/hailo-resnet-multitask/compile/{model_name}.hef"
with open(file_name, "wb") as f:
    f.write(hef)

har_path = f"/mnt/f/mit/hailo-resnet-multitask/compile/{model_name}_compiled_model.har"
runner.save_har(har_path)

