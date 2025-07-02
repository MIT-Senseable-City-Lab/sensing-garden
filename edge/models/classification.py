# General imports used throughout the tutorial
from multiprocessing import Process
import numpy as np
import argparse
from PIL import Image
import os

from hailo_platform import (
    HEF,
    ConfigureParams,
    FormatType,
    HailoSchedulingAlgorithm,
    HailoStreamInterface,
    InferVStreams,
    InputVStreamParams,
    InputVStreams,
    OutputVStreamParams,
    OutputVStreams,
    VDevice,
)


def softmax(x):
    """Convert logits to probabilities using softmax function"""
    e_x = np.exp(x - np.max(x))  # Subtract max for numerical stability
    return e_x / e_x.sum()

def infer_image(image_array, model_name="london_141-multitask", hef_path="./london_141-multitask.hef"):
    """
    Run inference on a single image using Hailo hardware
    
    Args:
        image_array: Numpy array representing the image
        model_name: Name of the model to use
        hef_path: Path to the HEF file, if None will use model_name.hef
        
    Returns:
        Dictionary containing inference results
    """
    if hef_path is None:
        hef_path = f"{model_name}.hef"
    
    # Setting VDevice params to disable the HailoRT service feature
    params = VDevice.create_params()
    params.scheduling_algorithm = HailoSchedulingAlgorithm.NONE

    # Create device
    target = VDevice(params=params)

    # Loading compiled HEFs to device
    hef = HEF(hef_path)

    # Get the "network groups" information from the .hef
    configure_params = ConfigureParams.create_from_hef(hef=hef, interface=HailoStreamInterface.PCIe)
    network_groups = target.configure(hef, configure_params)
    network_group = network_groups[0]
    network_group_params = network_group.create_params()

    # Create input and output virtual streams params
    input_vstreams_params = InputVStreamParams.make(network_group, quantized=False, format_type=FormatType.FLOAT32)
    output_vstreams_params = OutputVStreamParams.make(network_group, quantized=False, format_type=FormatType.FLOAT32)

    # Get input/output information
    input_vstream_info = hef.get_input_vstream_infos()[0]
    output_vstream_info = hef.get_output_vstream_infos()[0]
    
    # Ensure image has the right shape
    expected_shape = input_vstream_info.shape
    if image_array.shape != expected_shape:
        raise ValueError(f"Input image shape {image_array.shape} doesn't match expected shape {expected_shape}")
    
    # Add batch dimension for compatibility with the inference API
    input_data = {input_vstream_info.name: np.expand_dims(image_array, axis=0)}

    with InferVStreams(network_group, input_vstreams_params, output_vstreams_params) as infer_pipeline:
        with network_group.activate(network_group_params):
            infer_results = infer_pipeline.infer(input_data)
            
            # Apply softmax to convert logits to probabilities
            processed_results = {}
            for stream_name, result in infer_results.items():
                # Apply softmax to each batch item
                processed_results[stream_name] = np.array([softmax(item) for item in result])
                
            # Return results without batch dimension
            return {k: v[0] for k, v in processed_results.items()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run inference on an image using Hailo hardware")
    parser.add_argument("--image", required=True, help="Path to input JPG image")
    parser.add_argument("--model", default="resnet_v1_18", help="Model name")
    parser.add_argument("--hef", default=None, help="Path to HEF file")
    args = parser.parse_args()
    
    # Check if image exists
    if not os.path.exists(args.image):
        print(f"Error: Image file {args.image} not found")
        exit(1)
    
    # Load image
    img = Image.open(args.image)
    
    # Get expected input dimensions from the model
    if args.hef is None:
        hef_path = f"{args.model}.hef"
    else:
        hef_path = args.hef
    
    hef = HEF(hef_path)
    input_info = hef.get_input_vstream_infos()[0]
    target_height, target_width, channels = input_info.shape
    
    # Resize and convert image to the expected format
    img = img.resize((target_width, target_height))
    
    # Convert to RGB if needed
    if channels == 3 and img.mode != "RGB":
        img = img.convert("RGB")
    
    # Convert to numpy array and ensure float32 type
    img_array = np.array(img).astype(np.float32)
    
    # Run inference
    try:
        results = infer_image(img_array, args.model, args.hef)
        
        # Print results
        for stream_name, result in results.items():
            print(f"Output stream: {stream_name}")
            print(f"Shape: {result.shape}")
            print(f"Results (probabilities): {result}")
            
            # Also print top classes
            top_classes = np.argsort(result)[::-1][:5]  # Top 5 classes
            print(f"Top 5 classes: {top_classes}")
            print(f"Top 5 probabilities: {result[top_classes]}")
            print(f"Highest probability class: {np.argmax(result)} with probability: {np.max(result):.4f}")
    except Exception as e:
        print(f"Error during inference: {e}")
