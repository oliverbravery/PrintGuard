import asyncio
from typing import Annotated
from fastapi import APIRouter, File, UploadFile, Query
from ...core.inference import predict
from ...core.model import get_model
from ...core.models import PredictionResult
from ..crypto_utils import EncryptedRoute

router = APIRouter(route_class=EncryptedRoute)

@router.post("/predict")
async def predict_image(
    file: Annotated[UploadFile, File(description="Image to classify")],
    sensitivity: Annotated[float, Query(ge=0.1, le=10.0)] = 1.0
) -> PredictionResult:
    """Predict print defect class for an uploaded image."""
    contents = await file.read()
    model_info = get_model()
    result = await asyncio.to_thread(predict, contents, model_info, sensitivity)
    return PredictionResult(**result)
