const asciiTitle = document.getElementById('ascii-title');
const cameraTitle = document.getElementById('cameraTitle');
const camPredictionDisplay = document.getElementById('camPredictionDisplay');
const camPredictionTimeDisplay = document.getElementById('camPredictionTimeDisplay');
const camTotalDetectionsDisplay = document.getElementById('camTotalDetectionsDisplay');
const camFrameRateDisplay = document.getElementById('camFrameRateDisplay');
const camDetectionToggleButton = document.getElementById('camDetectionToggleButton');
const camDetectionLiveIndicator = document.getElementsByClassName('live-indicator');

const stopDetectionBtnLabel = 'Stop Detection';
const startDetectionBtnLabel = 'Start Detection';

function render_ascii_title(doc_element, text) {
    figlet.defaults({ fontPath: '/static/fonts/' });
    figlet.text(text, {
        font: 'Big Money-ne',
        horizontalLayout: 'default',
        verticalLayout: 'default'
    }, function(err, data) {
        if (err) {
            console.error(err);
            return;
        }
        doc_element.textContent = data;
    });
}

function updateRecentDetectionResult(result, doc_element) {
    doc_element.textContent = result || '-';
}

function updateRecentDetectionTime(last_time, doc_element) {
    try {
        if (!last_time) {throw 'exit';}
        const date = new Date(last_time * 1000);
        const timeString = date.toISOString().substr(11, 8);
        doc_element.textContent = timeString;
        return;
    } catch (e) {
        doc_element.textContent = '-';
    }
}

function updateTotalDetectionsCount(detection_times, doc_element) {
    if (!detection_times) {
        doc_element.textContent = '-';
        return;
    }
    doc_element.textContent = detection_times;
}

function updateFrameRate(fps, doc_element) {
    if (!fps) {
        doc_element.textContent = '-';
        return;
    }
    doc_element.textContent = fps.toFixed(2);
}

function toggleIsDetectingStatus(isActive) {
    if (isActive) {
        camDetectionLiveIndicator[0].style.backgroundColor = 'green';
    } else {
        camDetectionLiveIndicator[0].style.backgroundColor = 'red';
    }
}

function updateDetectionButton(isActive) {
    if (isActive) {
        camDetectionToggleButton.textContent = stopDetectionBtnLabel;
    } else {
        camDetectionToggleButton.textContent = startDetectionBtnLabel;
    }
}

function updatePolledDetectionData(d) {
    updateRecentDetectionResult(d.last_result, camPredictionDisplay);
    updateRecentDetectionTime(d.last_time, camPredictionTimeDisplay);
    updateTotalDetectionsCount(d.total_detections, camTotalDetectionsDisplay);
    updateFrameRate(d.frame_rate, camFrameRateDisplay);
    toggleIsDetectingStatus(d.live_detection_running);
    updateDetectionButton(d.live_detection_running);
}

function fetchAndUpdateMetricsForCamera(cameraIndexStr) {
    const cameraIdx = parseInt(cameraIndexStr, 10);
    fetch(`/live/camera`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_index: cameraIdx })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(`Failed to fetch camera state for camera ${cameraIdx}: ${errData.detail || response.statusText}`);
            }).catch(() => {
                throw new Error(`Failed to fetch camera state for camera ${cameraIdx}: ${response.statusText}`);
            });
        }
        return response.json();
    })
    .then(data => {
        const metricsData = {
            start_time: data.start_time,
            last_result: data.last_result,
            last_time: data.last_time,
            total_detections: data.detection_times ? data.detection_times.length : 0,
            frame_rate: null,
            live_detection_running: data.live_detection_running,
        };
        updatePolledDetectionData(metricsData);
    })
    .catch(error => {
        console.error(`Error fetching metrics for camera ${cameraIdx}:`, error.message);
        const emptyMetrics = {
            start_time: null, last_result: 'Error', last_time: null,
            total_detections: 0, frame_rate: null, live_detection_running: false
        };
        updatePolledDetectionData(emptyMetrics);
    });
}

function sendDetectionRequest(isStart) {
    fetch(`/live/${isStart ? 'start' : 'stop'}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ camera_index: selectedCamera })
    })
        .then(response => {
            if (response.ok) {
                return true;
            } else {
                console.error('Failed to start live detection');
            }
        })
        .catch(error => console.error('Error:', error));
    return false;
}

camDetectionToggleButton.addEventListener('click', function() {
    if (camDetectionToggleButton.textContent === startDetectionBtnLabel) {
        camDetectionToggleButton.textContent = stopDetectionBtnLabel;
        sendDetectionRequest(true);
    } else {
        camDetectionToggleButton.textContent = startDetectionBtnLabel;
        sendDetectionRequest(false);
    }
});

render_ascii_title(asciiTitle, 'FDM Sentinel');