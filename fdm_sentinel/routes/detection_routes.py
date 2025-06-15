import asyncio
import json
import logging
import time
from typing import List

import torch
from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..utils.camera_utils import get_camera_state, update_camera_state
from ..utils.detection_utils import _live_detection_loop
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
                # pylint: disable=W0718
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

@router.post("/detect/live/start")
async def start_live_detection(request: Request, camera_index: int = Body(..., embed=True)):
    camera_state = get_camera_state(camera_index)
    if camera_state.live_detection_running:
        return {"message": f"Live detection already running for camera {camera_index}"}
    else:
        await update_camera_state(camera_index, {
            "current_alert_id": None,
            "detection_history": [],
            "last_result": None,
            "last_time": None,
            "error": None
        })
    await update_camera_state(camera_index, {"start_time": time.time(),
                                       "live_detection_running": True,
                                       "live_detection_task": asyncio.create_task(
                                           _live_detection_loop(request.app.state, camera_index)
                                           )})
    return {"message": f"Live detection started for camera {camera_index}"}

@router.post("/detect/live/stop")
async def stop_live_detection(request: Request, camera_index: int = Body(..., embed=True)):
    camera_state = get_camera_state(camera_index)
    if not camera_state.live_detection_running:
        return {"message": f"Live detection not running for camera {camera_index}"}
    live_detection_task = camera_state.live_detection_task
    if live_detection_task:
        try:
            await asyncio.wait_for(live_detection_task, timeout=0.25)
            logging.debug("Live detection task for camera %d finished successfully.", camera_index)
        except asyncio.TimeoutError:
            logging.debug("Live detection task for camera %d did not finish in time.", camera_index)
            if live_detection_task:
                live_detection_task.cancel()
        except Exception as e:
            logging.error("Error stopping live detection task for camera %d: %s", camera_index, e)
        finally:
            live_detection_task = None
    await update_camera_state(camera_index, {"start_time": None,
                                    "live_detection_running": False,
                                    "live_detection_task": None})
    return {"message": f"Live detection stopped for camera {camera_index}"}
