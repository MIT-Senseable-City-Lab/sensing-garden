#!/usr/bin/env python3

import os
import sys
import numpy as np
from loguru import logger
import queue
import threading
from typing import List
from object_detection_utils import ObjectDetectionUtils

# Add the parent directory to the system path to access utils module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import HailoAsyncInference, validate_images

def preprocess_single_image(image: np.ndarray, input_queue: queue.Queue, width: int, height: int, utils: ObjectDetectionUtils) -> None:
    """
    Process a single image and enqueue it.
    """
    processed_image = utils.preprocess(image, width, height)
    input_queue.put(([image], [processed_image]))
    input_queue.put(None)  # Add sentinel value to signal end of input

def get_inference_results(output_queue: queue.Queue) -> np.ndarray:
    """
    Get inference results from the output queue.
    """
    result = output_queue.get()
    if result is None:
        return None

    _, infer_results = result
    
    # Deals with the expanded results from hailort versions < 4.19.0
    if len(infer_results) == 1:
        infer_results = infer_results[0]
    
    return infer_results

def infer_single_image(
    image: np.ndarray,
    net_path: str,
    labels_path: str,
) -> np.ndarray:
    """
    Run inference on a single image and return the results.

    Args:
        image: Numpy array image
        net_path (str): Path to the HEF model file.
        labels_path (str): Path to a text file containing labels.
    
    Returns:
        np.ndarray: Inference results
    """
    det_utils = ObjectDetectionUtils(labels_path)
    batch_size = 1
    
    # Validate images
    try:
        validate_images([image], batch_size)
    except ValueError as e:
        logger.error(e)
        return None
    
    input_queue = queue.Queue()
    output_queue = queue.Queue()

    hailo_inference = HailoAsyncInference(
        net_path, input_queue, output_queue, batch_size, send_original_frame=True
    )
    height, width, _ = hailo_inference.get_input_shape()

    preprocess_thread = threading.Thread(
        target=preprocess_single_image,
        args=(image, input_queue, width, height, det_utils)
    )
    
    preprocess_thread.start()
    hailo_inference.run()
    preprocess_thread.join()
    
    # Get the results
    results = get_inference_results(output_queue)
    output_queue.put(None)  # Signal process thread to exit
    
    return results

def run_inference(
    net: str = "yolov7.hef",
    input: str = "zidane.jpg",
    batch_size: int = 1,
    labels: str = "coco.txt",
    save_stream_output: bool = False
) -> np.ndarray:
    """
    Simplified run_inference function that only works with single image input
    and returns the inference results.
    """
    # Validate paths
    if not os.path.exists(net):
        raise FileNotFoundError(f"Network file not found: {net}")
    if not os.path.exists(labels):
        raise FileNotFoundError(f"Labels file not found: {labels}")
    
    # Only handle numpy array input now
    if isinstance(input, np.ndarray):
        return infer_single_image(input, net, labels)
    else:
        raise ValueError("This simplified version only accepts numpy array images")

