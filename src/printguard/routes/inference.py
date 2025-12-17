import asyncio
from typing import Annotated
from fastapi import APIRouter, File, UploadFile, Query
from ..inference import predict
from ..model import get_model
from ..models import PredictionResult

router = APIRouter()

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
