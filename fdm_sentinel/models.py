import json

class BaseModel:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
    def to_json(self):
        return json.dumps(self.__dict__)

class Alert(BaseModel):
    def __init__(self, id, snapshot, title, message, timestamp, countdown_time, camera_index):
        super().__init__(
            id=id,
            snapshot=snapshot,
            title=title,
            message=message,
            timestamp=timestamp,
            countdown_time=countdown_time,
            camera_index=camera_index
        )
