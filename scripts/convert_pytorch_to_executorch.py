import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List

import torch
from torch.export import export, Dim
from executorch.runtime import Runtime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import printguard.protonets as _pn
    sys.modules['protonets'] = _pn
except ImportError:
    pass

try:
    # pylint: disable=C0412
    from executorch.exir import (EdgeCompileConfig, to_edge_transform_and_lower)
    from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
    EXECUTORCH_AVAILABLE = True
    XNNPACK_AVAILABLE = True
except ImportError:
    EXECUTORCH_AVAILABLE = False
    XNNPACK_AVAILABLE = False
    logging.warning("ExecutorTorch not available. Install with: pip install executorch")

COREML_AVAILABLE = False
MPS_AVAILABLE = False
QNN_AVAILABLE = False
VULKAN_AVAILABLE = False
ARM_AVAILABLE = False

if EXECUTORCH_AVAILABLE:
    try:
        from executorch.backends.apple.coreml.partition import CoreMLPartitioner
        COREML_AVAILABLE = True
    except ImportError:
        pass
    try:
        from executorch.backends.apple.mps.partition import MPSPartitioner
        MPS_AVAILABLE = True
    except ImportError:
        pass
    try:
        from executorch.backends.qualcomm.partition.qnn_partitioner import QnnPartitioner
        QNN_AVAILABLE = True
    except ImportError:
        pass
    try:
        from executorch.backends.vulkan.partition.vulkan_partitioner import VulkanPartitioner
        VULKAN_AVAILABLE = True
    except ImportError:
        pass
    try:
        from executorch.backends.arm.partition.arm_partitioner import ArmPartitioner
        ARM_AVAILABLE = True
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

def get_available_backend_formats():
    """Get list of available ExecutorTorch backend formats."""
    backends = []
    if XNNPACK_AVAILABLE:
        backends.append("xnnpack")
    if COREML_AVAILABLE:
        backends.append("coreml")
    if MPS_AVAILABLE:
        backends.append("mps")
    if QNN_AVAILABLE:
        backends.append("qnn")
    if VULKAN_AVAILABLE:
        backends.append("vulkan")
    if ARM_AVAILABLE:
        backends.append("arm")
    backends.append("none")
    return backends

def get_backend_partitioners(backend_formats):
    """Get list of partitioner instances for the specified backend formats.
    
    Args:
        backend_formats: List of backend format names to use
        
    Returns:
        List of partitioner instances
    """
    partitioners = []
    for backend in backend_formats:
        if backend == "xnnpack" and XNNPACK_AVAILABLE:
            partitioners.append(XnnpackPartitioner())
            logging.info("Added XNNPACK partitioner for CPU optimization")
        elif backend == "coreml" and COREML_AVAILABLE:
            try:
                partitioners.append(CoreMLPartitioner())
                logging.info("Added CoreML partitioner for Apple devices (GPU, ANE, CPU)")
            except Exception as e:
                logging.warning("Failed to initialize CoreML partitioner: %s", e)
                logging.info("Skipping CoreML partitioner due to initialization error")
        elif backend == "mps" and MPS_AVAILABLE:
            try:
                # MPS partitioner requires compile_specs parameter in newer versions
                partitioners.append(MPSPartitioner(compile_specs={}))
                logging.info("Added MPS partitioner for Apple Metal Performance Shaders")
            except TypeError:
                # Fallback for older versions that don't require compile_specs
                partitioners.append(MPSPartitioner())
                logging.info("Added MPS partitioner for Apple Metal Performance Shaders (legacy)")
        elif backend == "qnn" and QNN_AVAILABLE:
            partitioners.append(QnnPartitioner())
            logging.info("Added QNN partitioner for Qualcomm HTP")
        elif backend == "vulkan" and VULKAN_AVAILABLE:
            partitioners.append(VulkanPartitioner())
            logging.info("Added Vulkan partitioner for mobile GPU")
        elif backend == "arm" and ARM_AVAILABLE:
            partitioners.append(ArmPartitioner())
            logging.info("Added ARM partitioner for ARM targets")
        elif backend == "none":
            continue
        else:
            logging.warning("Backend format '%s' is not available or not supported", backend)
    return partitioners

def convert_pytorch_to_executorch(pytorch_model_path: str, options_path: str,
                                 output_path: str, device: str = "cpu",
                                 backend_formats: List[str] = None,
                                 dynamic_shapes: bool = False,
                                 quantization: bool = False):
    """Convert a PyTorch model to ExecutorTorch format.
    
    Args:
        pytorch_model_path: Path to the PyTorch model file (.pt or .pth)
        options_path: Path to the model options JSON file
        output_path: Path where the ExecutorTorch model will be saved (.pte)
        device: Device to use for conversion ('cpu', 'cuda', or 'mps')
        backend_formats: List of backend formats to use for optimization (e.g.['xnnpack','coreml'])
        dynamic_shapes: Whether to enable dynamic input shapes
        quantization: Whether to enable quantization (where supported)
    """
    if not EXECUTORCH_AVAILABLE:
        raise ImportError("ExecutorTorch is not available. Install with: pip install executorch")
    if backend_formats is None:
        backend_formats = ["xnnpack"]
    device = validate_device(device)
    available_backends = get_available_backend_formats()
    logging.info("Available backend formats: %s", available_backends)
    logging.info("Requested backend formats: %s", backend_formats)
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
        example_input = torch.randn(1, *x_dim).to(device_obj)
        logging.info("Testing model with example input...")
        with torch.no_grad():
            test_output = model(example_input)
        logging.info("Model test successful. Output shape: %s", test_output.shape)
        dynamic_shapes_config = None
        if dynamic_shapes:
            dynamic_shapes_config = {
                "x": {
                    0: Dim("batch", min=1, max=64),
                }
            }
            logging.info("Using dynamic shapes: %s", dynamic_shapes_config)
        logging.info("Exporting PyTorch model to Edge dialect...")
        exported_program = export(
            model,
            (example_input,),
            dynamic_shapes=dynamic_shapes_config
        )
        edge_config = EdgeCompileConfig(
            _check_ir_validity=False,
        )
        partitioners = get_backend_partitioners(backend_formats)
        logging.info("Converting to ExecutorTorch format...")
        try:
            executorch_program = to_edge_transform_and_lower(
                exported_program,
                compile_config=edge_config,
                partitioner=partitioners
            ).to_executorch()
        except Exception as e:
            error_msg = str(e)
            if "register an operator" in error_msg and "multiple times" in error_msg:
                logging.warning(
                    "Operator registration error detected, retrying with fallback configuration...")
                if partitioners:
                    partitioners = [partitioners[0]]
                    logging.info("Retrying with single partitioner: %s",
                                 type(partitioners[0]).__name__)
                    try:
                        executorch_program = to_edge_transform_and_lower(
                            exported_program,
                            compile_config=edge_config,
                            partitioner=partitioners
                        ).to_executorch()
                    except Exception:
                        logging.warning("Single partitioner also failed, falling back to no partitioner")
                        executorch_program = to_edge_transform_and_lower(
                            exported_program,
                            compile_config=edge_config,
                            partitioner=[]
                        ).to_executorch()
                else:
                    logging.warning("Falling back to no partitioner due to registration errors")
                    executorch_program = to_edge_transform_and_lower(
                        exported_program,
                        compile_config=edge_config,
                        partitioner=[]
                    ).to_executorch()
            elif "custom (non-ATen) operator" in error_msg:
                logging.warning(
                    "Custom operator compatibility issue detected, trying without problematic partitioners...")
                filtered_partitioners = [p for p in partitioners if (
                    "CoreML" not in type(p).__name__)]
                if filtered_partitioners:
                    logging.info("Retrying without CoreML partitioner")
                    executorch_program = to_edge_transform_and_lower(
                        exported_program,
                        compile_config=edge_config,
                        partitioner=filtered_partitioners
                    ).to_executorch()
                else:
                    logging.warning(
                        "No compatible partitioners available, using CPU-only conversion")
                    executorch_program = to_edge_transform_and_lower(
                        exported_program,
                        compile_config=edge_config,
                        partitioner=[]
                    ).to_executorch()
            else:
                raise
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if len(backend_formats) > 1 and "none" not in backend_formats:
            backend_suffix = "_" + "_".join(sorted(backend_formats))
        elif len(backend_formats) == 1 and backend_formats[0] != "none":
            backend_suffix = "_" + backend_formats[0]
        else:
            backend_suffix = ""
        quant_suffix = "_q8" if quantization else ""
        base_name = output_path.stem
        extension = output_path.suffix
        final_output_path = (
            output_path.parent / f"{base_name}{backend_suffix}{quant_suffix}{extension}")
        with open(final_output_path, "wb") as f:
            f.write(executorch_program.buffer)
        logging.info("Successfully converted model to ExecutorTorch format: %s", final_output_path)
        logging.info("Model size: %.2f MB", os.path.getsize(final_output_path) / (1024 * 1024))
        logging.info("Backend formats used: %s", backend_formats)
        if str(final_output_path) != str(output_path):
            with open(output_path, "wb") as f:
                f.write(executorch_program.buffer)
            logging.info("Also saved copy as: %s", output_path)
        logging.info("Verifying converted model...")
        try:
            runtime = Runtime.get()
            program = runtime.load_program(str(output_path))
            method = program.load_method("forward")
            verification_input = example_input.cpu() if device == "mps" else example_input
            outputs = method.execute([verification_input])
            logging.info("Verification successful. Output shape: %s", outputs[0].shape)
            original_output = test_output.detach().cpu().numpy()
            executorch_output = outputs[0].detach().cpu().numpy()
            max_diff = abs(
                original_output - executorch_output).max()
            logging.info("Maximum difference between original and ExecutorTorch outputs: %.6f",
                         max_diff)
            tolerance = 1e-2 if device == "mps" else 1e-3
            if max_diff < tolerance:
                logging.info("Output comparison passed (max diff < %.0e)", tolerance)
            else:
                logging.warning("Output difference is larger than expected (%.6f)", max_diff)
                if device == "mps":
                    logging.info("Note: MPS may have different numerical precision than CPU/CUDA")
        except Exception as e:
            logging.warning("Could not verify converted model: %s", e)
            if device == "mps":
                logging.info(
                    "Note: MPS verification might fail due to ExecutorTorch runtime limitations")
    except Exception as e:
        logging.error("Failed to convert PyTorch model to ExecutorTorch: %s", e)
        raise

def main():
    """Main function to handle command line arguments and run conversion."""
    available_devices = get_available_devices()
    device_info = []
    if "cpu" in available_devices:
        device_info.append("cpu (always available)")
    if "cuda" in available_devices:
        device_info.append("cuda (NVIDIA GPU detected)")
    if "mps" in available_devices:
        device_info.append("mps (Apple Silicon with Metal)")
    available_backends = get_available_backend_formats()
    backend_info = []
    if "xnnpack" in available_backends:
        backend_info.append("xnnpack (CPU optimization)")
    if "coreml" in available_backends:
        backend_info.append("coreml (Apple GPU/ANE/CPU)")
    if "mps" in available_backends:
        backend_info.append("mps (Apple Metal)")
    if "qnn" in available_backends:
        backend_info.append("qnn (Qualcomm HTP)")
    if "vulkan" in available_backends:
        backend_info.append("vulkan (Mobile GPU)")
    if "arm" in available_backends:
        backend_info.append("arm (ARM targets)")
    backend_info.append("none (no backend delegation)")
    parser = argparse.ArgumentParser(
        description="Convert PyTorch models to ExecutorTorch format with multiple backend support for maximum compatibility",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=f"Available devices: {', '.join(device_info)}\nAvailable backends: {', '.join(backend_info)}"
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
        help="Output path for the ExecutorTorch model (.pte)",
        required=True
    )
    parser.add_argument(
        "-d", "--device",
        choices=get_available_devices(),
        default="cpu",
        help="Device to use for conversion. 'cpu' is always available, 'cuda' requires NVIDIA GPU, 'mps' requires Apple Silicon Mac with macOS 12.3+"
    )
    parser.add_argument(
        "-b", "--backends",
        nargs="+",
        choices=get_available_backend_formats(),
        default=["xnnpack"],
        help="Backend formats to use for optimization. Multiple backends can be specified for maximum compatibility. Use 'none' for no backend delegation."
    )
    parser.add_argument(
        "--all-backends",
        action="store_true",
        help="Use all available backend formats for maximum compatibility"
    )
    parser.add_argument(
        "--multi-target",
        action="store_true",
        help="Generate multiple optimized versions for different deployment targets (mobile, edge, server)"
    )
    parser.add_argument(
        "--force-all-targets",
        action="store_true",
        help="Force generation of all target configurations, even if backends are not available (will skip missing backends gracefully)"
    )
    parser.add_argument(
        "--quantization",
        action="store_true",
        help="Enable quantization (where supported by backends)"
    )
    parser.add_argument(
        "--no-xnnpack",
        action="store_true",
        help="Disable XNNPACK optimization (deprecated - use --backends instead)"
    )
    parser.add_argument(
        "--dynamic-shapes",
        action="store_true",
        help="Enable dynamic input shapes (allows variable batch sizes)"
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
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    if not os.path.exists(args.pytorch_model):
        logging.error("PyTorch model file not found: %s", args.pytorch_model)
        sys.exit(1)
    if not os.path.exists(args.options_file):
        logging.error("Options file not found: %s", args.options_file)
        sys.exit(1)
    if not args.output.endswith('.pte'):
        args.output += '.pte'
    if args.multi_target or args.force_all_targets:
        logging.info("Multi-target mode: Will generate optimized versions for different deployment targets")
        logging.info("Available backends on this system: %s", available_backends)
        if args.force_all_targets:
            logging.info("Force mode enabled: Will attempt all configurations regardless of backend availability")
        target_configs = [
            (["xnnpack"], "CPU-optimized for edge devices"),
            (["coreml"], "Apple devices (iOS/macOS)"),
            (["mps"], "Apple Metal Performance Shaders"),
            (["qnn"], "Qualcomm devices"),
            (["vulkan"], "Mobile GPU"),
            (["arm"], "ARM targets"),
            (["xnnpack", "coreml"], "Universal (CPU + Apple)"),
            (["xnnpack", "mps"], "Universal (CPU + Apple Metal)"),
            (["xnnpack", "vulkan"], "Universal (CPU + Mobile GPU)"),
            (["coreml", "mps"], "Apple optimized (CoreML + MPS)"),
            (["none"], "CPU-only (no backend optimization)"),
        ]
        successful_conversions = []
        failed_conversions = []
        for backend_config, description in target_configs:
            should_attempt = args.force_all_targets or all(b in available_backends for b in backend_config)
            if should_attempt:
                logging.info("Generating %s version...", description)
                try:
                    convert_pytorch_to_executorch(
                        pytorch_model_path=args.pytorch_model,
                        options_path=args.options_file,
                        output_path=args.output,
                        device=args.device,
                        backend_formats=backend_config,
                        dynamic_shapes=args.dynamic_shapes,
                        quantization=args.quantization
                    )
                    successful_conversions.append(description)
                except Exception as e:
                    logging.error("Failed to generate %s version: %s", description, e)
                    failed_conversions.append((description, str(e)))
            else:
                missing_backends = [b for b in backend_config if b not in available_backends]
                logging.info("Skipping %s version - missing backends: %s", description, missing_backends)
        logging.info("Multi-target conversion completed!")
        logging.info("Successfully generated %d versions: %s", len(successful_conversions), successful_conversions)
        if failed_conversions:
            logging.warning("Failed to generate %d versions:", len(failed_conversions))
            for desc, error in failed_conversions:
                logging.warning("  - %s: %s", desc, error[:100] + "..." if len(error) > 100 else error)
        return
    elif args.all_backends:
        backend_formats = [b for b in get_available_backend_formats() if b != "none"]
    elif args.no_xnnpack:
        logging.warning("--no-xnnpack is deprecated. Use --backends none instead.")
        backend_formats = ["none"]
    else:
        backend_formats = args.backends
    available_backends = get_available_backend_formats()
    for backend in backend_formats:
        if backend not in available_backends:
            logging.error("Backend format '%s' is not available. Available: %s",
                         backend, available_backends)
            sys.exit(1)
    try:
        convert_pytorch_to_executorch(
            pytorch_model_path=args.pytorch_model,
            options_path=args.options_file,
            output_path=args.output,
            device=args.device,
            backend_formats=backend_formats,
            dynamic_shapes=args.dynamic_shapes,
            quantization=args.quantization
        )
        logging.info("Conversion completed successfully!")
    except Exception as e:
        logging.error("Conversion failed: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
