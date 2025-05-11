from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
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
        "sensitivity": config.SENSITIVITY,
        "camera_index": config.CAMERA_INDEX,
        "brightness": config.BRIGHTNESS,
        "contrast": config.CONTRAST,
        "focus": config.FOCUS,
        "countdown_time": config.COUNTDOWN_TIME,
        "warning_intervals": ",".join(str(x) for x in config.WARNING_INTERVALS),
    })

@settings_router.post("/settings", include_in_schema=False)
async def update_settings(request: Request,
    sensitivity: float = Form(...),
    camera_index: int = Form(...),
    brightness: float = Form(...),
    contrast: float = Form(...),
    focus: float = Form(...),
    countdown_time: int = Form(...),
    warning_intervals: str = Form(...),
):
    config.SENSITIVITY = sensitivity
    config.CAMERA_INDEX = camera_index
    config.BRIGHTNESS = brightness
    config.CONTRAST = contrast
    config.FOCUS = focus
    config.COUNTDOWN_TIME = countdown_time
    config.WARNING_INTERVALS = [int(x) for x in warning_intervals.split(",") if x.strip().isdigit()]
    return RedirectResponse("/settings", status_code=303)

def generate_frames():
    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    while True:
        success, frame = cap.read()
        if not success:
            break
        frame = cv2.convertScaleAbs(frame, alpha=config.CONTRAST, beta=int((config.BRIGHTNESS - 1.0) * 255))
        if config.FOCUS and config.FOCUS != 1.0:
            blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=config.FOCUS)
            frame = cv2.addWeighted(frame, 1.0 + config.FOCUS, blurred, -config.FOCUS, 0)
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    cap.release()

@settings_router.get('/camera_feed', include_in_schema=False)
async def camera_feed():
    return StreamingResponse(generate_frames(), media_type='multipart/x-mixed-replace; boundary=frame')

@settings_router.post('/settings/update_video', include_in_schema=False)
async def update_video_settings(request: Request):
    data = await request.json()
    if 'brightness' in data:
        config.BRIGHTNESS = float(data['brightness'])
    if 'contrast' in data:
        config.CONTRAST = float(data['contrast'])
    if 'focus' in data:
        config.FOCUS = float(data['focus'])
    return JSONResponse({'status': 'ok'})
