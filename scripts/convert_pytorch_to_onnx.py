import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.onnx
import onnxruntime as ort

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import printguard.utils.backends.protonets as _pn
    sys.modules['protonets'] = _pn
except ImportError:
    pass


def get_available_devices():
    """Get list of available devices for model conversion."""
    devices = ["cpu"]
    if torch.cuda.is_available():
        devices.append("cuda")
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        devices.append("mps")
    return devices

def validate_device(device: str):
    """Validate if the requested device is available."""
    available_devices = get_available_devices()
    if device not in available_devices:
        if device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA is not available on this system")
        elif device == "mps" and not (
            torch.backends.mps.is_available() and torch.backends.mps.is_built()):
            raise ValueError(
                "MPS is not available on this system. Requires macOS 12.3+ and Apple Silicon")
        else:
            raise ValueError(
                f"Device '{device}' is not available. Available devices: {available_devices}")
    return device


def convert_pytorch_to_onnx(pytorch_model_path: str, options_path: str,
                           output_path: str, device: str = "cpu"):
    """Convert a PyTorch model to ONNX format.
    
    Args:
        pytorch_model_path: Path to the PyTorch model file (.pt or .pth)
        options_path: Path to the model options JSON file
        output_path: Path where the ONNX model will be saved
        device: Device to use for conversion ('cpu', 'cuda', or 'mps')
    """
    device = validate_device(device)
    try:
        logging.info("Loading PyTorch model from %s", pytorch_model_path)
        device_obj = torch.device(device)
        if device == "mps":
            logging.info("Using MPS (Metal Performance Shaders) for acceleration")
        elif device == "cuda":
            logging.info("Using CUDA GPU: %s", torch.cuda.get_device_name())
        else:
            logging.info("Using CPU for conversion")
        full_model = torch.load(pytorch_model_path, map_location=device_obj, weights_only=False)
        if hasattr(full_model, 'encoder'):
            model = full_model.encoder
            logging.info("Extracted encoder from Protonet model")
        else:
            model = full_model
            logging.info("Using full model (no encoder attribute found)")
        model.eval()
        with open(options_path, 'r', encoding='utf-8') as f:
            model_opt = json.load(f)
        x_dim = list(map(int, model_opt['model.x_dim'].split(',')))
        logging.info("Model input dimensions: %s", x_dim)
        dummy_input = torch.randn(1, *x_dim).to(device_obj)
        logging.info("Testing model with dummy input...")
        with torch.no_grad():
            test_output = model(dummy_input)
        logging.info("Model test successful. Output shape: %s", test_output.shape)
        export_params = {
            "input_names": ["input"],
            "output_names": ["output"],
            "dynamic_axes": {
                "input": {0: "batch_size"},
                "output": {0: "batch_size"}
            },
            "opset_version": 11,
            "do_constant_folding": True,
            "export_params": True,
        }
        logging.info("Converting to ONNX format...")
        torch.onnx.export(
            model,
            dummy_input,
            output_path,
            **export_params
        )
        logging.info("ONNX model saved to %s", output_path)
        try:
            logging.info("Verifying ONNX model...")
            session = ort.InferenceSession(output_path)
            dummy_input_numpy = dummy_input.detach().cpu().numpy()
            output = session.run(None, {"input": dummy_input_numpy})
            logging.info("ONNX model verification successful")
            logging.info("Output shape: %s", output[0].shape)
            pytorch_output = test_output.detach().cpu().numpy()
            onnx_output = output[0]
            max_diff = np.max(np.abs(pytorch_output - onnx_output))
            logging.info("Maximum difference between PyTorch and ONNX outputs: %.6f", max_diff)
            if max_diff < 1e-5:
                logging.info("PyTorch and ONNX outputs are very close (diff < 1e-5)")
            elif max_diff < 1e-3:
                logging.info("PyTorch and ONNX outputs are close (diff < 1e-3)")
            else:
                logging.warning("PyTorch and ONNX outputs differ significantly (diff = %.6f)",
                                max_diff)
        except ImportError:
            logging.warning("ONNX Runtime not available. Skipping verification.")
        except Exception as e:
            logging.error("ONNX model verification failed: %s", e)
            raise
    except Exception as e:
        logging.error("Failed to convert model: %s", e)
        raise

def main():
    """Main function to handle command line arguments and run conversion."""
    # Get available devices for help text
    available_devices = get_available_devices()
    device_info = []
    if "cpu" in available_devices:
        device_info.append("cpu (always available)")
    if "cuda" in available_devices:
        device_info.append("cuda (NVIDIA GPU detected)")
    if "mps" in available_devices:
        device_info.append("mps (Apple Silicon with Metal)")
    parser = argparse.ArgumentParser(
        description="Convert PyTorch models to ONNX format for PrintGuard",
        epilog=f"Available devices on this system: {', '.join(device_info)}"
    )
    parser.add_argument(
        "pytorch_model", 
        help="Path to the PyTorch model file (.pt or .pth)"
    )
    parser.add_argument(
        "options_file", 
        help="Path to the model options JSON file"
    )
    parser.add_argument(
        "-o", "--output", 
        help="Output path for the ONNX model (default: same name with .onnx extension)"
    )
    parser.add_argument(
        "-d", "--device", 
        choices=get_available_devices(),
        default="cpu",
        help="Device to use for conversion. 'cpu' is always available, 'cuda' requires NVIDIA GPU, 'mps' requires Apple Silicon Mac with macOS 12.3+"
    )
    parser.add_argument(
        "-v", "--verbose", 
        action="store_true",
        help="Enable verbose logging"
    )
    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    if args.output:
        output_path = args.output
    else:
        pytorch_path = Path(args.pytorch_model)
        output_path = str(pytorch_path.with_suffix('.onnx'))
    if not os.path.exists(args.pytorch_model):
        logging.error("PyTorch model file not found: %s", args.pytorch_model)
        sys.exit(1)
    if not os.path.exists(args.options_file):
        logging.error("Options file not found: %s", args.options_file)
        sys.exit(1)
    try:
        convert_pytorch_to_onnx(
            args.pytorch_model,
            args.options_file,
            output_path,
            args.device
        )
        logging.info("Conversion completed successfully!")
    except Exception as e:
        logging.error("Conversion failed: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
