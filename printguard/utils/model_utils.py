import asyncio
from typing import Any
import logging
from PIL import Image
from fastapi import HTTPException, UploadFile

from .config import SENSITIVITY

async def _run_inference(model: torch.nn.Module,
                         batch_tensor: torch.Tensor,
                         prototypes: Any,
                         defect_idx: int,
                         device: torch.device) -> Any:
    """Run model inference on a batch of image tensors.

    Args:
        model (torch.nn.Module): The neural network model to use.
        batch_tensor (torch.Tensor): Batch of preprocessed image tensors.
        prototypes (Any): Class prototype tensors for comparison.
        defect_idx (int): Index of the defect class.
        device (torch.device): Device to run inference on.

    Returns:
        Any: Inference results (typically class predictions).

    Raises:
        TypeError: If the model doesn't have required methods.
        RuntimeError: If inference execution fails.
    """
    if not hasattr(model, 'eval'):
        raise TypeError("Provided model object does not have an 'eval' method.")
    model.eval()

    loop = asyncio.get_running_loop()
    try:
        with torch.no_grad():
            results = await loop.run_in_executor(
                None,
                predict_batch,
                model,
                batch_tensor,
                prototypes,
                defect_idx,
                SENSITIVITY,
                device
            )
        return results
    except Exception as e:
        logging.error("Error during inference execution: %s", e)
        raise RuntimeError(f"Inference execution failed: {e}") from e
