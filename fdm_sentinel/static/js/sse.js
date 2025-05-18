const evtSource = new EventSource('https://localhost:8000/sse');
const notificationPopup = document.getElementById('notificationPopup');
const notificationMessage = document.getElementById('notificationMessage');
const notificationImage = document.getElementById('notificationImage');
const notificationCountdownTimer = document.getElementById('notificationCountdownTimer');
const dismissNotificationBtn = document.getElementById('dismissNotificationBtn');
const cancelPrintBtn = document.getElementById('cancelPrintBtn');

let currentAlertId = null;

document.addEventListener('DOMContentLoaded', loadPendingAlerts);

function getLocalActiveAlerts() {
    try {
        return JSON.parse(localStorage.getItem('activeAlerts')) || {};
    } catch (e) {
        console.error("Error parsing activeAlerts from localStorage:", e);
        return {};
    }
}

function getRemoteActiveAlerts() {
    return fetch('/alert/active', {
        method: 'GET',
    })
        .then(response => response.json())
        .then(data => data.active_alerts || [])
        .catch(error => {
            console.error("Error fetching remote active alerts:", error);
            return [];
        });
}

function saveActiveAlert(alert) {
    const activeAlerts = getLocalActiveAlerts();
    const expirationTime = Date.now() + (alert.countdown_time || 10) * 1000;
    activeAlerts[alert.id] = {
        data: alert,
        expirationTime: expirationTime
    };
    localStorage.setItem('activeAlerts', JSON.stringify(activeAlerts));
}

function removeActiveAlert(alertId) {
    const activeAlerts = getLocalActiveAlerts();
    if (activeAlerts[alertId]) {
        delete activeAlerts[alertId];
        localStorage.setItem('activeAlerts', JSON.stringify(activeAlerts));
    }
}

async function loadPendingAlerts() {
    const activeAlerts = getLocalActiveAlerts();
    const now = Date.now();
    let alertsRemaining = false;
    const remoteAlerts = await getRemoteActiveAlerts();
    const remoteAlertIds = remoteAlerts.map(alert => alert.id);
    Object.keys(activeAlerts).forEach(alertId => {
        if (activeAlerts[alertId].expirationTime < now || !remoteAlertIds.includes(alertId)) {
            delete activeAlerts[alertId];
        }
    });
    remoteAlerts.forEach(remoteAlert => {
        if (!activeAlerts[remoteAlert.id]) {
            const alert_start_time = new Date(remoteAlert.timestamp);
            const expirationTime = alert_start_time + (remoteAlert.countdown_time * 1000);
            activeAlerts[remoteAlert.id] = {
                data: remoteAlert,
                expirationTime: expirationTime
            };
        }
    });
    localStorage.setItem('activeAlerts', JSON.stringify(activeAlerts));
    const alertIds = Object.keys(activeAlerts);
    if (alertIds.length > 0) {
        const alertId = alertIds[0];
        const alert = activeAlerts[alertId].data;
        alert.countdown_time = Math.max(1, Math.floor((activeAlerts[alertId].expirationTime - now) / 1000));
        displayAlert(alert);
        alertsRemaining = alertIds.length > 1;
    }
    return alertsRemaining;
}

function displayAlert(alert_data) {
    const parsedData = parseAlertData(alert_data);
    updateAlertUI(parsedData);
    startAlertCountdown(parsedData);
    saveActiveAlert(parsedData);
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
    const startTime = Date.now();
    const countdownTime = Math.max(10, data.countdown_time || 0);
    const endTime = startTime + countdownTime * 1000;
    function updateCountdown() {
        const now = Date.now();
        let secondsLeft = Math.max(0, Math.round((endTime - now) / 1000));
        notificationCountdownTimer.textContent = `${secondsLeft}s remaining`;
        const activeAlerts = getLocalActiveAlerts();
        if (activeAlerts[data.id]) {
            activeAlerts[data.id].expirationTime = endTime;
            localStorage.setItem('activeAlerts', JSON.stringify(activeAlerts));
        }
        if (secondsLeft <= 0) {
            clearInterval(window.countdownInterval);
            if (notificationPopup.style.display !== 'none') {
                notificationPopup.style.display = 'none';
                removeActiveAlert(currentAlertId);
                loadPendingAlerts();
            }
        }
    }
    updateCountdown();
    window.countdownInterval = setInterval(updateCountdown, 1000);
}

evtSource.onmessage = (e) => {
    try {
        let packet_data = JSON.parse(e.data);
        packet_data = packet_data.data;
        if (packet_data) {
            if (packet_data.event == "alert") {
                displayAlert(packet_data.data);
            }
            else if (packet_data.event == "camera_state") {
                const cameraData = packet_data.data;
                if (!cameraData.camera_index && cameraData.camera_index !== 0) {
                    console.warn("Camera data missing camera_index", cameraData);
                }
                if (typeof cameraData.live_detection_running !== 'boolean') {
                    cameraData.live_detection_running = !!cameraData.live_detection_running;
                }
                document.dispatchEvent(new CustomEvent('cameraStateUpdated', {
                    detail: cameraData
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
                removeActiveAlert(currentAlertId);
                loadPendingAlerts();
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