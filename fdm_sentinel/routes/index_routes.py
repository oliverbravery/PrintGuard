import time

from fastapi import Form, Request, APIRouter
from fastapi.responses import RedirectResponse

from ..utils.config import CAMERA_INDEX

router = APIRouter()

@router.get("/", include_in_schema=False)
async def serve_index(request: Request):
    # pylint: disable=import-outside-toplevel
    from ..app import app, templates
    camera_index = list(app.state.camera_states.keys())[0] if (
        app.state.camera_states
        ) else CAMERA_INDEX
    return templates.TemplateResponse("index.html", {
        "camera_states": app.state.camera_states,
        "request": request,
        "camera_index": camera_index,
        "current_time": time.time(),
    })

# pylint: disable=unused-argument
@router.post("/", include_in_schema=False)
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
    # pylint: disable=import-outside-toplevel
    from ..utils.camera_utils import update_camera_state
    await update_camera_state(camera_index, {
        "sensitivity": sensitivity,
        "brightness": brightness,
        "contrast": contrast,
        "focus": focus,
        "countdown_time": countdown_time,
        "majority_vote_threshold": majority_vote_threshold,
        "majority_vote_window": majority_vote_window,
    })
    return RedirectResponse("/", status_code=303)
