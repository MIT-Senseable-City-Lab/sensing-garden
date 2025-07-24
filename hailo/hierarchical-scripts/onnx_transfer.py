import torch
import torch.nn as nn
import os
import numpy as np
import torchvision.models as models
import onnxruntime

class HierarchicalInsectClassifier(nn.Module):
    def __init__(self, num_classes_per_level=None):
        super(HierarchicalInsectClassifier, self).__init__()
        
        self.backbone = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
        backbone_output_features = self.backbone.fc.in_features
        self.backbone.fc = nn.Identity()
        
        # Create branches with the correct structure
        self.branches = nn.ModuleList()
        if num_classes_per_level:
            for num_classes in num_classes_per_level:
                branch = nn.Sequential(
                    nn.Linear(backbone_output_features, 512),
                    nn.ReLU(),
                    nn.Dropout(0.5),
                    nn.Linear(512, num_classes)
                )
                self.branches.append(branch)
                
        # Add these attributes with correct shapes to match the trained model
        # Calculate total number of classes across all levels
        total_classes = sum(num_classes_per_level) #if num_classes_per_level else 295  # Use 295 as fallback
        self.register_buffer("class_means", torch.zeros(total_classes))
        self.register_buffer("class_stds", torch.zeros(total_classes))
        
    def forward(self, x):
        features = self.backbone(x)
        
        outputs = []
        for branch in self.branches:
            outputs.append(branch(features))
            
        return outputs

# Add the verification function
def verify_onnx_weights(pytorch_model, onnx_model_path, input_data=None):
    """
    Verify that ONNX model produces same results as PyTorch model
    """
    print("Verifying ONNX model against PyTorch model...")
    
    # If input data not provided, create random input
    if input_data is None:
        input_data = torch.randn(1, 3, 640, 640)
    
    # Run PyTorch inference
    pytorch_model.eval()
    with torch.no_grad():
        pt_outputs = pytorch_model(input_data)
    
    # Run ONNX inference
    ort_session = onnxruntime.InferenceSession(onnx_model_path)
    ort_inputs = {ort_session.get_inputs()[0].name: input_data.numpy()}
    ort_outputs = ort_session.run(None, ort_inputs)
    
    # Compare outputs
    print("\nComparing outputs:")
    max_diffs = []
    for i, (pt_out, ort_out) in enumerate(zip(pt_outputs, ort_outputs)):
        # Convert PyTorch tensor to numpy for comparison
        pt_out_np = pt_out.numpy()
        
        # Calculate difference
        diff = np.abs(pt_out_np - ort_out)
        max_diff = np.max(diff)
        max_diffs.append(max_diff)
        
        print(f"Output {i} - Max Difference: {max_diff}")
        print(f"  PyTorch shape: {pt_out_np.shape}, ONNX shape: {ort_out.shape}")
        print(f"  PyTorch output: {pt_out_np.flatten()[:5]} ...")
        print(f"  ONNX output: {ort_out.flatten()[:5]} ...")
    
    overall_match = all(diff < 1e-4 for diff in max_diffs)
    if overall_match:
        print("\n✅ ONNX model outputs match PyTorch model within tolerance!")
    else:
        print("\n❌ ONNX model outputs differ from PyTorch model!")
    
    return overall_match

try:
    # Load the trained model
    checkpoint_path = "/mnt/f/mit/hailo-resnet-multitask/ptonnx/london_141-multitask.pt"
    print(f"Loading model from: {checkpoint_path}")
    
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    
    # Extract taxonomy information to determine number of classes
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        # Direct class count detection from model_state_dict
        state_dict = checkpoint["model_state_dict"]
        
        # Look for branch output layer dimensions
        num_classes = []
        branch_idx = 0
        while f"branches.{branch_idx}.3.weight" in state_dict:
            output_shape = state_dict[f"branches.{branch_idx}.3.weight"].shape
            num_classes.append(output_shape[0])
            branch_idx += 1
            
        if num_classes:
            print(f"Detected classes from model weights: {num_classes}")
        else:
            # Fallback to taxonomy extraction if available
            taxonomy = checkpoint.get("taxonomy", None)
            species_list = checkpoint.get("species_list", None)
            
            if taxonomy and species_list:
                # Automatically determine number of classes for each level
                orders = set()
                families = set()
                species = set(species_list)
                
                # Extract unique orders and families from taxonomy
                for item in taxonomy:
                    # Check if item is a list or tuple before using len()
                    if isinstance(item, (list, tuple)) and len(item) >= 3:
                        orders.add(item[0])
                        families.add(item[1])
                    elif isinstance(item, dict) and all(k in item for k in ['order', 'family', 'species']):
                        # Handle case where taxonomy items might be dictionaries
                        orders.add(item['order'])
                        families.add(item['family'])
                    else:
                        print(f"Warning: Skipping taxonomy item with unexpected format: {type(item)} - {item}")
                
                num_classes = [len(orders), len(families), len(species)]
                print(f"Automatically detected classes from taxonomy: Order={num_classes[0]}, Family={num_classes[1]}, Species={num_classes[2]}")
    
    if not num_classes or 0 in num_classes:
        # Try to infer from model structure
        print("Attempting to infer class counts from model structure...")
        
        # Examine state_dict keys and structure more thoroughly
        if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
            state_dict = checkpoint["model_state_dict"]
            
            # Method 1: Find all final branch layers
            branch_counts = []
            for key in state_dict.keys():
                if ".3.weight" in key and key.startswith("branches."):
                    branch_idx = int(key.split('.')[1])
                    if branch_idx + 1 > len(branch_counts):
                        branch_counts.extend([0] * (branch_idx + 1 - len(branch_counts)))
                    branch_counts[branch_idx] = state_dict[key].shape[0]
            
            if all(count > 0 for count in branch_counts) and len(branch_counts) > 0:
                num_classes = branch_counts
                print(f"Successfully inferred class counts from model layers: {num_classes}")
            else:
                # Method 2: If available, use the output layers to determine shapes
                output_layers = [k for k in state_dict.keys() if k.endswith(".weight") and "branches" in k]
                if output_layers:
                    # Sort by branch index for consistency
                    output_layers.sort()
                    num_classes = [state_dict[layer].shape[0] for layer in output_layers if layer.endswith(".3.weight")]
                    if num_classes:
                        print(f"Inferred class counts from output layers: {num_classes}")
        
        # If still not determined, raise error instead of using hardcoded values
        if not num_classes or 0 in num_classes:
            raise ValueError("Could not automatically determine number of classes. Please specify manually.")
    
    # Initialize model with correct number of classes
    model = HierarchicalInsectClassifier(num_classes_per_level=num_classes)
    
    # Load weights
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        # Use strict=True to ensure all keys are loaded
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
        print("Successfully loaded model from state dict")
        
        # Optional: print taxonomy information if available
        if "taxonomy" in checkpoint:
            print(f"Model contains taxonomy for {len(checkpoint['species_list'])} species")
            print(f"Species: {checkpoint['species_list']}")
    else:
        model = checkpoint
        print("Loaded model directly")
    
    model.eval()
    
    # Create dummy input tensor with 640x640 image size
    input_shape = (1, 3, 224, 224)
    dummy_input = torch.randn(input_shape)
    
    # Export to ONNX
    onnx_file = "/mnt/f/mit/hailo-resnet-multitask/ptonnx/london_141-multitask.onnx"
    
    print(f"Exporting model with input shape {input_shape} to {onnx_file}...")
    torch.onnx.export(
        model,
        dummy_input,
        onnx_file,
        export_params=True,
        opset_version=11,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["family", "genus", "species"]
    )
    
    # Check if file was created
    if os.path.exists(onnx_file):
        print(f"Successfully created {onnx_file} ({os.path.getsize(onnx_file)/1024/1024:.2f} MB)")
        
        # Verify the ONNX model against the PyTorch model
        verify_onnx_weights(model, onnx_file, dummy_input)
    else:
        print(f"Failed to create {onnx_file}")

except Exception as e:
    print(f"Error: {str(e)}")
    import traceback
    traceback.print_exc()
