import asyncio
from typing import Any
import logging

from .config import SENSITIVITY
from .inference_lib import get_inference_engine

async def _run_inference(model: Any,
                         batch_tensor: Any,
                         prototypes: Any,
                         defect_idx: int,
                         device: Any) -> Any:
    """Run model inference on a batch of image tensors.

    Args:
        model (Any): The neural network model to use.
        batch_tensor (Any): Batch of preprocessed image tensors.
        prototypes (Any): Class prototype tensors for comparison.
        defect_idx (int): Index of the defect class.
        device (Any): Device to run inference on.

    Returns:
        Any: Inference results (typically class predictions).

    Raises:
        TypeError: If the model doesn't have required methods.
        RuntimeError: If inference execution fails.
    """
    inference_engine = get_inference_engine()
    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(
            None,
            inference_engine.predict_batch,
            model,
            batch_tensor,
            prototypes,
            defect_idx,
            SENSITIVITY,
            str(device)
        )
        return results
    except Exception as e:
        logging.error("Error during inference execution: %s", e)
        raise RuntimeError(f"Inference execution failed: {e}") from e
