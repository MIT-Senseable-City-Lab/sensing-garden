import numpy as np
import os
from PIL import Image
from hailo_sdk_client import ClientRunner


def create_image_dataset(images_dir, save_path=None):
    """
    Creates a numpy array from a directory of already-resized images.
    
    Args:
        images_dir (str): Path to directory containing images
        save_path (str, optional): Path to save the numpy array. If None, array is not saved.
        
    Returns:
        np.ndarray: Numpy array of shape (num_images, height, width, channels)
    """
    # Get list of jpg images
    images_list = [img_name for img_name in os.listdir(images_dir) if os.path.splitext(img_name)[1] == ".jpg"]
    
    # Read first image to get dimensions
    sample_img = np.array(Image.open(os.path.join(images_dir, images_list[0])))
    height, width, channels = sample_img.shape
    
    # Initialize dataset array
    dataset = np.zeros((len(images_list), height, width, channels))
    
    # Load all images into the array
    for idx, img_name in enumerate(sorted(images_list)):
        img = np.array(Image.open(os.path.join(images_dir, img_name)))
        dataset[idx, :, :, :] = img
    
    # Save dataset if path is provided
    if save_path:
        np.save(save_path, dataset)
        
    return dataset

calib_dataset = create_image_dataset("/mnt/f/mit/hailo-resnet-multitask/optimise/calibration_224", "./calib_set.npy")

# Example usage:
model_name = "london_141-multitask"
hailo_model_har_name = f"/mnt/f/mit/hailo-resnet-multitask/parsing/{model_name}_hailo_model.har"
assert os.path.isfile(hailo_model_har_name), "Please provide valid path for HAR file"
runner = ClientRunner(har=hailo_model_har_name)

# Now we will create a model script, that tells the compiler to add a normalization on the beginning
# of the model (that is why we didn't normalize the calibration set;
# Otherwise we would have to normalize it before using it)

# Batch size is 8 by default
alls = "normalization1 = normalization([123.675, 116.28, 103.53], [58.395, 57.12, 57.375])\n"

# Load the model script to ClientRunner so it will be considered on optimization
runner.load_model_script(alls)

# Call Optimize to perform the optimization process
runner.optimize(calib_dataset)

# Save the result state to a Quantized HAR file
quantized_model_har_path = f"/mnt/f/mit/hailo-resnet-multitask/optimise/{model_name}_quantized_model.har"
runner.save_har(quantized_model_har_path)