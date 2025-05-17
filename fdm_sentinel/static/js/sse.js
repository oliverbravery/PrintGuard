const evtSource = new EventSource('https://localhost:8000/sse');
const notificationPopup = document.getElementById('notificationPopup');
const notificationMessage = document.getElementById('notificationMessage');
const dismissNotificationBtn = document.getElementById('dismissNotificationBtn');
const cancelPrintBtn = document.getElementById('cancelPrintBtn');

let currentAlertId = null;

function displayAlert(alert_data, seenAlerts) {
    alert_data = JSON.parse(alert_data);
    currentAlertId = alert_data.id;
    notificationMessage.textContent = `New alert: ${alert_data.message}`;
    notificationPopup.style.display = 'block';
    seenAlerts.push(alert_data.id);
    document.cookie = `seen_alerts=${seenAlerts.join(",")}; path=/; max-age=3600`;
}

evtSource.onmessage = (e) => {
    try {
        let packet_data = JSON.parse(e.data);
        packet_data = packet_data.data;
        const seenAlerts = document.cookie.match(/seen_alerts=([^;]+)/)?.[1]?.split(",") || [];
        if (packet_data) {
            if (packet_data.event == "alert" && !seenAlerts.includes(packet_data.data.id)) {
                displayAlert(packet_data.data, seenAlerts);
            }
            else if (packet_data.event == "camera_state" && typeof updatePolledDetectionData === "function") {
                window.dispatchEvent(new CustomEvent('cameraStateUpdated', {
                detail: packet_data.data
                }));
            }
        }
    } catch (error) {
        console.error("Error processing SSE message:", error);
    }
};

evtSource.onerror = (err) => {
    console.error("SSE error", err);
};

function dismissAlert(action_type) {
    fetch(`/alert/dismiss`, { 
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ alert_id: currentAlertId, action: action_type })
    })
        .then(response => {
            if (response.ok) {
                notificationPopup.style.display = 'none';
            } else {
                console.error('Failed to dismiss alert');
            }
        })
        .catch(error => console.error('Error:', error));
}

dismissNotificationBtn.addEventListener('click', () => {
    dismissAlert('dismiss');
});

cancelPrintBtn.addEventListener('click', () => {
    dismissAlert('cancel_print');
});