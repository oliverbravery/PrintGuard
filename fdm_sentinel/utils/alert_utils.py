async def alert_generator():
    from ..app import app
    while True:
        alert = await app.state.alert_queue.get()
        print(f"Alert generated: {alert}")
        yield alert

async def append_new_alert(alert):
    from ..app import app
    app.state.alerts[alert["alert_id"]] = alert
    await app.state.alert_queue.put(alert)