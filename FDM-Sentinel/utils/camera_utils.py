import asyncio
import json
import time
import uuid
import numpy as np

import cv2
import utils.config as config
from PIL import Image
from fastapi import WebSocket, WebSocketDisconnect

from utils.config import (
    CAMERA_INDEX, DETECTION_WINDOW, DETECTION_THRESHOLD, BASE_URL
)
from utils.model_utils import _run_inference

alerts = {}

async def _webcam_generator(model, transform, device, class_names, prototypes, defect_idx, camera_index, app_state):
    from app import get_camera_state
    
    camera_state = get_camera_state(camera_index)
    
    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            print(f"Warning: Cannot open camera at index {camera_index}")
            # Instead of raising an error, yield an error message and exit
            yield f"data: {json.dumps({'error': f'Cannot open camera {camera_index}', 'camera_index': camera_index})}\n\n"
            return
            
        while True:
            ret, frame = cap.read()
            if not ret:
                print(f"Warning: Failed to read frame from camera {camera_index}")
                break
            frame = cv2.convertScaleAbs(frame, alpha=config.CONTRAST, beta=int((config.BRIGHTNESS - 1.0) * 255))
            if config.FOCUS and config.FOCUS != 1.0:
                blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=config.FOCUS)
                frame = cv2.addWeighted(frame, 1.0 + config.FOCUS, blurred, -config.FOCUS, 0)
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tensor = transform(image).unsqueeze(0).to(device)
            prediction = await _run_inference(model, tensor, prototypes, defect_idx, device)
            numeric = prediction[0] if isinstance(prediction, list) else prediction
            label = class_names[numeric] if isinstance(numeric, int) and 0 <= numeric < len(class_names) else str(numeric)
            current_time = time.time()

            camera_state["last_result"] = label
            camera_state["last_time"] = current_time
            
            rst = {
                "time": current_time, 
                "result": label, 
                "camera_index": camera_index
            }
            yield f"data: {json.dumps(rst)}\n\n"
            await asyncio.sleep(0.1)
    finally:
        cap.release()

async def _live_detection_loop(app_state, camera_index):
    from utils.notification_utils import send_defect_notification
    from app import get_camera_state
    
    camera_state = get_camera_state(camera_index)
    
    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            print(f"Cannot open camera at index {camera_index}")
            camera_state["error"] = f"Cannot open camera {camera_index}"
            camera_state["live_detection_running"] = False
            return

        camera_state["error"] = None
        
        while camera_state["live_detection_running"]:
            ret, frame = cap.read()
            if not ret:
                break
            frame = cv2.convertScaleAbs(frame, alpha=config.CONTRAST, beta=int((config.BRIGHTNESS - 1.0) * 255))
            if config.FOCUS and config.FOCUS != 1.0:
                blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=config.FOCUS)
                frame = cv2.addWeighted(frame, 1.0 + config.FOCUS, blurred, -config.FOCUS, 0)
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tensor = app_state.transform(image).unsqueeze(0).to(app_state.device)
            try:
                prediction = await _run_inference(app_state.model, tensor, app_state.prototypes, app_state.defect_idx, app_state.device)
                numeric = prediction[0] if isinstance(prediction, list) else prediction
            except Exception as e:
                print(f"Live loop inference error for camera {camera_index}: {e}")
                numeric = None

            label = app_state.class_names[numeric] if isinstance(numeric, int) and 0 <= numeric < len(app_state.class_names) else str(numeric)
            camera_state["last_result"] = label
            camera_state["last_time"] = time.time()
            
            if isinstance(numeric, int) and numeric == app_state.defect_idx:
                now = time.time()
                camera_state["detection_times"].append(now)
                while camera_state["detection_times"] and now - camera_state["detection_times"][0] > DETECTION_WINDOW:
                    camera_state["detection_times"].popleft()
                
                if len(camera_state["detection_times"]) >= DETECTION_THRESHOLD and camera_state["current_alert_id"] is None:
                    alert_id = f"{camera_index}_{str(uuid.uuid4())}"
                    _, img_buf = cv2.imencode('.jpg', frame)
                    alerts[alert_id] = {
                        'timestamp': now,
                        'snapshot': img_buf.tobytes(),
                        'camera_index': camera_index
                    }
                    camera_state["current_alert_id"] = alert_id
                    send_defect_notification(alert_id, BASE_URL, camera_index=camera_index)
            await asyncio.sleep(0.1)
    finally:
        cap.release()

async def websocket_camera_feed_handler(websocket: WebSocket):
    await websocket.accept()
    try:
        from app import get_camera_state
        camera_state = get_camera_state(CAMERA_INDEX)

        try:
            cap = cv2.VideoCapture(CAMERA_INDEX)
            start_time = time.time()
            while not cap.isOpened() and time.time() - start_time < 3:
                await asyncio.sleep(0.1)
                cap.release()
                cap = cv2.VideoCapture(CAMERA_INDEX)
                
            if not cap.isOpened():
                print(f"Cannot open camera at index {CAMERA_INDEX} for websocket feed")
                camera_state["error"] = f"Cannot open camera {CAMERA_INDEX}"
                error_frame = create_error_image(f"Camera {CAMERA_INDEX} not available")
                _, buf = cv2.imencode('.jpg', error_frame)
                await websocket.send_bytes(buf.tobytes())
                await asyncio.sleep(1)
                return

            camera_state["error"] = None

            failure_count = 0
            max_failures = 5
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    failure_count += 1
                    print(f"Failed to read frame from camera {CAMERA_INDEX} (attempt {failure_count}/{max_failures})")

                    if failure_count >= max_failures:
                        error_frame = create_error_image(f"Camera {CAMERA_INDEX} read error")
                        _, buf = cv2.imencode('.jpg', error_frame)
                        await websocket.send_bytes(buf.tobytes())
                        break

                    await asyncio.sleep(0.5)
                    continue

                failure_count = 0

                frame = cv2.convertScaleAbs(frame, alpha=config.CONTRAST, beta=int((config.BRIGHTNESS - 1.0) * 255))
                if config.FOCUS and config.FOCUS != 1.0:
                    blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=config.FOCUS)
                    frame = cv2.addWeighted(frame, 1.0 + config.FOCUS, blurred, -config.FOCUS, 0)
                _, buf = cv2.imencode('.jpg', frame)
                await websocket.send_bytes(buf.tobytes())
                await asyncio.sleep(0.1)
                
        except Exception as e:
            print(f"Error accessing camera {CAMERA_INDEX}: {e}")
            camera_state["error"] = f"Camera error: {str(e)}"
            error_frame = create_error_image(f"Camera {CAMERA_INDEX} error: {str(e)}")
            _, buf = cv2.imencode('.jpg', error_frame)
            await websocket.send_bytes(buf.tobytes())
            
    except WebSocketDisconnect:
        print("Camera feed WebSocket disconnected")
    except Exception as e:
        print(f"Error in websocket camera feed: {e}")
    finally:
        if 'cap' in locals() and cap is not None:
            cap.release()
            
def create_error_image(message, width=640, height=480):
    """Create an image with an error message"""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img.fill(64)
    
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_size = cv2.getTextSize(message, font, 1, 2)[0]
    
    x = (width - text_size[0]) // 2
    y = (height + text_size[1]) // 2
    
    cv2.putText(img, message, (x, y), font, 1, (255, 255, 255), 2)
    
    return img
