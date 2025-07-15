const evtSource = new EventSource('/sse');
const notificationPopup = document.getElementById('notificationPopup');
const notificationMessage = document.getElementById('notificationMessage');
const notificationImage = document.getElementById('notificationImage');
const notificationCountdownTimer = document.getElementById('notificationCountdownTimer');
const dismissNotificationBtn = document.getElementById('dismissNotificationBtn');
const cancelPrintBtn = document.getElementById('cancelPrintBtn');
const pausePrintBtn = document.getElementById('pausePrintBtn');

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
    const remoteAlerts = await getRemoteActiveAlerts();
    const remoteAlertIds = remoteAlerts.map(alert => alert.id);
    
    Object.keys(activeAlerts).forEach(alertId => {
        if (activeAlerts[alertId].expirationTime < now || !remoteAlertIds.includes(alertId)) {
            delete activeAlerts[alertId];
        }
    });
    
    remoteAlerts.forEach(remoteAlert => {
        if (!activeAlerts[remoteAlert.id]) {
            const alert_start_time = remoteAlert.timestamp * 1000;
            const expirationTime = alert_start_time + (remoteAlert.countdown_time * 1000);
            activeAlerts[remoteAlert.id] = {
                data: remoteAlert,
                expirationTime: expirationTime
            };
        }
    });
    
    localStorage.setItem('activeAlerts', JSON.stringify(activeAlerts));
    const alertIds = Object.keys(activeAlerts);

    alertIds.forEach(alertId => {
        const alert = activeAlerts[alertId].data;
        alert.countdown_time = Math.max(1, Math.floor((activeAlerts[alertId].expirationTime - now) / 1000));
        displayAlert(alert);
    });
    
    return alertIds.length > 0;
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
    const notificationsContainer = document.getElementById('notificationsContainer');

    if (document.getElementById(`alert-${data.id}`)) {
        return;
    }

    const alertElement = document.createElement('div');
    alertElement.id = `alert-${data.id}`;
    alertElement.className = 'alert-item';
    alertElement.style.padding = '10px';
    alertElement.style.marginBottom = '10px';
    alertElement.style.borderBottom = '1px solid #dee2e6';
    let alertContent = `<p>${data.message}</p>`;
    alertContent += `<p id="countdown-${data.id}"></p>`;

    if (data.snapshot) {
        alertContent = `<img src="data:image/jpeg;base64,${data.snapshot}" 
                            style="width:100%;margin-bottom:10px;" />` + alertContent;
    }
    const hasPrinter = data.has_printer === true;
    alertContent += `<div>
        <button class="dismiss-btn" data-alert-id="${data.id}">Dismiss</button>
        <button class="suspend-print-btn${!hasPrinter ? ' disabled' : ''}" 
                data-alert-id="${data.id}"
                ${!hasPrinter ? 'disabled' : ''}>Cancel Print</button>
        <button class="suspend-print-btn${!hasPrinter ? ' disabled' : ''}" 
                data-alert-id="${data.id}"
                ${!hasPrinter ? 'disabled' : ''}>Pause Print</button>
    </div>`;
    
    alertElement.innerHTML = alertContent;
    notificationsContainer.prepend(alertElement);

    alertElement.querySelector('.dismiss-btn').addEventListener('click', () => {
        dismissAlert('dismiss', data.id);
    });
    
    const cancelBtns = alertElement.querySelectorAll('.suspend-print-btn');
    if (hasPrinter && cancelBtns.length >= 1) {
        cancelBtns[0].addEventListener('click', () => {
            dismissAlert('cancel_print', data.id);
        });
    }

    if (hasPrinter && cancelBtns.length >= 2) {
        cancelBtns[1].addEventListener('click', () => {
            dismissAlert('pause_print', data.id);
        });
    }

    notificationPopup.style.display = 'block';
}

function startAlertCountdown(data) {
    if (!data.id) return;
    
    const countdownElement = document.getElementById(`countdown-${data.id}`);
    if (!countdownElement) return;
    
    const countdownTimerId = `countdown-timer-${data.id}`;
    if (window[countdownTimerId]) {
        clearInterval(window[countdownTimerId]);
    }
    
    const startTime = Date.now();
    const countdownTime = data.countdown_time || 0;
    const endTime = startTime + countdownTime * 1000;

    function updateCountdown() {
        const now = Date.now();
        let secondsLeft = Math.max(0, Math.round((endTime - now) / 1000));
        countdownElement.textContent = `${secondsLeft}s remaining`;
        
        const activeAlerts = getLocalActiveAlerts();
        if (activeAlerts[data.id]) {
            activeAlerts[data.id].expirationTime = endTime;
            localStorage.setItem('activeAlerts', JSON.stringify(activeAlerts));
        }
        if (secondsLeft <= 0) {
            clearInterval(window[countdownTimerId]);
            const action = data.countdown_action || 'pause_print';
            if (action === 'cancel_print' && data.has_printer) {
                executeAlertAction('cancel_print', data.id);
            } else if (action === 'pause_print' && data.has_printer) {
                executeAlertAction('pause_print', data.id);
            } else {
                executeAlertAction('dismiss', data.id);
            }
        }
    }
    
    updateCountdown();
    window[countdownTimerId] = setInterval(updateCountdown, 1000);
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
                if (!cameraData.camera_uuid) {
                    console.warn("Camera data missing camera_uuid", cameraData);
                }
                if (typeof cameraData.live_detection_running !== 'boolean') {
                    cameraData.live_detection_running = !!cameraData.live_detection_running;
                }
                document.dispatchEvent(new CustomEvent('cameraStateUpdated', {
                    detail: cameraData
                }));
            }
            else if (packet_data.event == "printer_state") {
                const printerData = packet_data.data;
                document.dispatchEvent(new CustomEvent('printerStateUpdated', {
                    detail: printerData
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

function executeAlertAction(action_type, alertId) {
    fetch(`/alert/dismiss`, { 
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ alert_id: alertId, action: action_type })
    })
        .then(response => {
            if (response.ok) {
                const alertElement = document.getElementById(`alert-${alertId}`);
                if (alertElement) alertElement.remove();
                removeActiveAlert(alertId);

                if (document.getElementById('notificationsContainer').children.length === 0) {
                    notificationPopup.style.display = 'none';
                }
            } else {
                console.error('Failed to execute alert action');
            }
        })
        .catch(error => console.error('Error:', error));
}

function dismissAlert(action_type, alertId) {
    if (!alertId) alertId = currentAlertId;
    executeAlertAction(action_type, alertId);
}

document.addEventListener('DOMContentLoaded', () => {
    const dismissBtn = document.getElementById('dismissNotificationBtn');
    const cancelBtn = document.getElementById('cancelPrintBtn');
    const pauseBtn = document.getElementById('pausePrintBtn');
    if (dismissBtn) dismissBtn.remove();
    if (cancelBtn) cancelBtn.remove();
    if (pauseBtn) pauseBtn.remove();
});