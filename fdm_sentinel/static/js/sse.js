const evtSource = new EventSource('https://localhost:8000/sse');
const notificationPopup = document.getElementById('notificationPopup');
const notificationMessage = document.getElementById('notificationMessage');
const notificationImage = document.getElementById('notificationImage');
const notificationCountdownTimer = document.getElementById('notificationCountdownTimer');
const dismissNotificationBtn = document.getElementById('dismissNotificationBtn');
const cancelPrintBtn = document.getElementById('cancelPrintBtn');

let currentAlertId = null;

function displayAlert(alert_data, seenAlerts) {
    const parsedData = parseAlertData(alert_data);
    updateAlertUI(parsedData);
    startAlertCountdown(parsedData);
    markAlertAsSeen(parsedData.id, seenAlerts);
}

function parseAlertData(alert_data) {
    return typeof alert_data === 'string' ? JSON.parse(alert_data) : alert_data;
}

function updateAlertUI(data) {
    currentAlertId = data.id;
    notificationMessage.textContent = `New alert: ${data.message}`;
    if (data.snapshot) {
        notificationImage.src = `data:image/jpeg;base64,${data.snapshot}`;
        notificationImage.style.display = 'block';
    } else {
        notificationImage.style.display = 'none';
        notificationImage.src = '';
    }
    
    notificationPopup.style.display = 'block';
}

function startAlertCountdown(data) {
    if (window.countdownInterval) {
        clearInterval(window.countdownInterval);
    }
    const startTime = data.timestamp ? data.timestamp * 1000 : Date.now();
    const countdownTime = Math.max(10, data.countdown_time || 0);
    const endTime = startTime + countdownTime * 1000;
    function updateCountdown() {
        const now = Date.now();
        let secondsLeft = Math.max(0, Math.round((endTime - now) / 1000));
        notificationCountdownTimer.textContent = `${secondsLeft}s remaining`;
        
        if (secondsLeft <= 0) {
            clearInterval(window.countdownInterval);
            if (notificationPopup.style.display !== 'none') {
                notificationPopup.style.display = 'none';
            }
        }
    }
    
    updateCountdown();
    window.countdownInterval = setInterval(updateCountdown, 1000);
}

function markAlertAsSeen(alertId, seenAlerts) {
    seenAlerts.push(alertId);
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