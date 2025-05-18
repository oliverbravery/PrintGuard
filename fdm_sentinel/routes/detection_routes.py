import asyncio
import io
import json
from typing import List
import logging
import torch
from fastapi import (APIRouter,
                     File,
                     HTTPException,
                     UploadFile,
                     WebSocket,
                     WebSocketDisconnect,
                     Request)
from fastapi.responses import StreamingResponse
from PIL import Image

from ..utils.model_utils import _process_image, _run_inference

router = APIRouter()

@router.post("/detect")
async def detect_ep(request: Request, files: List[UploadFile] = File(...), stream: bool = False):
    app_state = request.app.state
    if (app_state.model is None or 
        app_state.transform is None or 
        app_state.device is None or 
        app_state.prototypes is None):
        raise HTTPException(status_code=503, 
                            detail="Model not loaded or not ready. Service unavailable.")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    process_tasks = [_process_image(file, app_state.transform, app_state.device) for file in files]
    try:
        image_tensors = await asyncio.gather(*process_tasks, return_exceptions=False)
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error("Unexpected error during image processing: %s", e)
        raise HTTPException(status_code=500, 
                            detail="An unexpected error occurred while processing images.") from e

    if not image_tensors:
        raise HTTPException(status_code=400, detail="No images could be successfully processed.")

    if stream and len(files) > 1:
        async def stream_generator():
            for i, tensor in enumerate(image_tensors):
                result_obj = {"filename": files[i].filename}
                try:
                    single_batch_tensor = tensor.unsqueeze(0)
                    prediction = await _run_inference(
                        app_state.model,
                        single_batch_tensor,
                        app_state.prototypes,
                        app_state.defect_idx,
                        app_state.device)
                    numeric = prediction[0] if isinstance(prediction, list) else prediction
                    label = app_state.class_names[numeric] if (
                            isinstance(numeric, int)
                            and 0 <= numeric < len(app_state.class_names)
                        ) else str(numeric)
                    result_obj["result"] = label
                except Exception as e:
                    logging.error("Error during streaming inference for %s: %s",
                                  files[i].filename, e)
                    result_obj["error"] = f"Inference failed: {str(e)}"
                try:
                    yield json.dumps(result_obj) + "\n"
                except TypeError as e:
                    logging.error("Serialization error for %s: %s", files[i].filename, e)
                    result_obj.pop("result", None)
                    result_obj["error"] = f"Serialization error: {str(e)}"
                    yield json.dumps(result_obj) + "\n"
                await asyncio.sleep(0.01)
        return StreamingResponse(stream_generator(), media_type="application/x-ndjson")
    else:
        batch_tensor = torch.stack(image_tensors)
        try:
            results = await _run_inference(app_state.model,
                                           batch_tensor,
                                           app_state.prototypes,
                                           app_state.defect_idx,
                                           app_state.device)
            if not isinstance(results, list) or len(results) != len(files):
                logging.warning("Mismatch between number of results (%d) and files (%d).", 
                                len(results) if isinstance(results, list) else 'N/A', len(files))
            output = []
            for i, file in enumerate(files):
                numeric = results[i] if isinstance(results, list) and i < len(results) else None
                label = app_state.class_names[numeric] if (
                        isinstance(numeric, int)
                        and 0 <= numeric < len(app_state.class_names)
                    ) else None
                result_entry = {
                    "filename": file.filename,
                    "result": label
                }
                if numeric is None:
                    result_entry["error"] = "Result missing or inference output mismatch"
                output.append(result_entry)
            return output
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        except Exception as e:
            logging.error("Unexpected error during batch inference: %s", e)
            raise HTTPException(status_code=500, detail=f"Inference failed: {e}") from e

@router.websocket("/ws/detect")
async def websocket_detect_ep(websocket: WebSocket):
    await websocket.accept()
    app_state = websocket.app.state
    if (app_state.model is None or 
        app_state.transform is None or 
        app_state.device is None or 
        app_state.prototypes is None):
        await websocket.close(code=1011, reason="Model not loaded or not ready.")
        return
    try:
        while True:
            data = await websocket.receive_bytes()
            image = Image.open(io.BytesIO(data)).convert("RGB")
            tensor = app_state.transform(image).unsqueeze(0).to(app_state.device)
            prediction = await _run_inference(app_state.model,
                                              tensor,
                                              app_state.prototypes,
                                              app_state.defect_idx,
                                              app_state.device)
            numeric = prediction[0] if isinstance(prediction, list) else prediction
            label = app_state.class_names[numeric] if (
                    isinstance(numeric, int)
                    and 0 <= numeric < len(app_state.class_names)
                ) else str(numeric)
            await websocket.send_json({"result": label})
    except WebSocketDisconnect:
        logging.debug("WebSocket disconnected")
    except Exception as e:
        logging.error("Error in WebSocket detection: %s", e)
        await websocket.close(code=1011, reason=f"Server error: {e}")
