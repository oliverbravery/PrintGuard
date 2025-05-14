class Alert:
    def __init__(self, id, snapshot, title, message, timestamp, countdown_time, camera_index):
        self.id = id
        self.snapshot = snapshot
        self.message = message
        self.title = title
        self.timestamp = timestamp
        self.camera_index = camera_index
        self.countdown_time = countdown_time