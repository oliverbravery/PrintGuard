import asyncio
import io
from typing import Any

import torch
from PIL import Image
from fastapi import HTTPException, UploadFile

from utils.inference_lib import predict_batch
from utils.config import SENSITIVITY

async def _process_image(file: UploadFile, transform: Any, device: torch.device) -> torch.Tensor:
    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents)).convert("RGB")
        tensor = transform(image).to(device)
        return tensor
    except Exception as e:
        print(f"Error processing image {file.filename}: {e}")
        raise HTTPException(status_code=400, detail=f"Error processing image {file.filename}. Invalid image format or data.") from e

async def _run_inference(model: torch.nn.Module, batch_tensor: torch.Tensor, prototypes: Any, defect_idx: int, device: torch.device) -> Any:
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
        print(f"Error during inference execution: {e}")
        raise RuntimeError(f"Inference execution failed: {e}") from e
