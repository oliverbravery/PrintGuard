from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from ..utils import config
import cv2
import os
from fastapi.templating import Jinja2Templates

template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=template_dir)

settings_router = APIRouter()

@settings_router.get("/settings", include_in_schema=False)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "camera_states": request.app.state.camera_states,
        "camera_index": config.CAMERA_INDEX,
    })

@settings_router.post("/settings", include_in_schema=False)
async def update_settings(request: Request,
                          camera_index: int = Form(...),
                          sensitivity: float = Form(...),
                          brightness: float = Form(...),
                          contrast: float = Form(...),
                          focus: float = Form(...),
                          countdown_time: int = Form(...),
                          majority_vote_threshold: int = Form(...),
                          majority_vote_window: int = Form(...),
                          ):
    from ..app import update_camera_state
    update_camera_state(camera_index, {
        "sensitivity": sensitivity,
        "brightness": brightness,
        "contrast": contrast,
        "focus": focus,
        "countdown_time": countdown_time,
        "majority_vote_threshold": majority_vote_threshold,
        "majority_vote_window": majority_vote_window,
    })
    return RedirectResponse("/settings", status_code=303)

def generate_frames(camera_index: int):
    from ..app import get_camera_state
    cap = cv2.VideoCapture(camera_index)
    camera_state = get_camera_state(camera_index)
    contrast = camera_state.get("contrast", config.CONTRAST)
    brightness = camera_state.get("brightness", config.BRIGHTNESS)
    focus = camera_state.get("focus", config.FOCUS)
    
    while True:
        success, frame = cap.read()
        if not success:
            break
        frame = cv2.convertScaleAbs(frame, alpha=contrast, beta=int((brightness - 1.0) * 255))
        if focus and focus != 1.0:
            blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=focus)
            frame = cv2.addWeighted(frame, 1.0 + focus, blurred, -focus, 0)
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    cap.release()

@settings_router.get('/camera_feed/{camera_index}', include_in_schema=False)
async def camera_feed(camera_index: int):
    return StreamingResponse(generate_frames(camera_index), media_type='multipart/x-mixed-replace; boundary=frame')
