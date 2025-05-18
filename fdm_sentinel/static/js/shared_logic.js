const cameraStatsContainer = document.getElementById('cameraStatsContainer');
const cameraStates = {};
const cameraDetailPanel = document.getElementById('cameraDetailPanel');
const cameraDetailTitle = document.getElementById('cameraDetailTitle');
const cameraDetailStats = document.getElementById('cameraDetailStats');
const cameraLiveFeedImage = document.getElementById('cameraLiveFeedImage');
const overlay = document.getElementById('overlay');
const startStopCameraBtn = document.getElementById('startStopCameraBtn');
const cancelPrintFromDetailBtn = document.getElementById('cancelPrintFromDetailBtn');
const closeCameraDetailBtn = document.getElementById('closeCameraDetailBtn');

let currentCameraIndex = null;
let liveFeedInterval = null;

document.addEventListener('cameraStateUpdated', function(event) {
    const cameraData = event.detail;
    if (cameraData && !cameraData.camera_index && cameraData.camera_index !== 0) {
        console.warn("Camera data missing camera_index", cameraData);
    }
    updateCameraTile(cameraData);
});

function updateCameraTile(cameraData) {
    const cameraIndex = cameraData.camera_index || 0;
    const cameraId = `camera-${cameraIndex}`;
    cameraStates[cameraId] = cameraData;
    let cameraTile = document.getElementById(cameraId);

    if (!cameraTile) {
        cameraTile = document.createElement('div');
        cameraTile.id = cameraId;
        cameraTile.className = 'camera-stats-tile';
        cameraTile.style.cursor = 'pointer';
        cameraTile.addEventListener('click', () => showCameraDetail(cameraIndex));
        cameraStatsContainer.appendChild(cameraTile);
    }

    const isActive = cameraData.live_detection_running === true;
    const statusClass = isActive ? 'camera-status-active' : 'camera-status-inactive';
    const lastResult = cameraData.last_result || 'N/A';
    const predictionClass = lastResult === 'success' ? 'prediction-success' : (lastResult === 'failure' ? 'prediction-failure' : '');
    let timeDisplay = 'Never';

    if (cameraData.last_time) {
        const date = new Date(cameraData.last_time * 1000);
        timeDisplay = date.toLocaleTimeString();
    }

    cameraTile.innerHTML = `
        <h3>
            <span class="camera-status-indicator ${statusClass}"></span>
            Camera ${cameraIndex}
        </h3>
        <p class="camera-stats-detail">Status: <span>${isActive ? 'Active' : 'Inactive'}</span></p>
        <p class="camera-stats-detail">Last prediction: <span class="${predictionClass}">${lastResult}</span></p>
        <p class="camera-stats-detail">Last detection: <span>${timeDisplay}</span></p>
    `;
}

fetchCameraStates();
setInterval(fetchCameraStates, 10000);

function fetchCameraStates() {
    const cameraIndexes = [0, 1];
    
    cameraIndexes.forEach(index => {
        fetch('/live/camera', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ camera_index: index })
        })
        .then(response => {
            if (response.ok) return response.json();
            throw new Error('Failed to fetch camera state');
        })
        .then(data => {
            data.camera_index = index;
            if (data.live_detection_running === undefined) {
                data.live_detection_running = false;
            }
            
            updateCameraTile(data);
        })
        .catch(error => {
            console.error(`Error fetching camera ${index} state:`, error);
        });
    });
}

function showCameraDetail(cameraIndex) {
    currentCameraIndex = cameraIndex;
    const cameraId = `camera-${cameraIndex}`;
    const cameraData = cameraStates[cameraId];
    
    cameraDetailTitle.textContent = `Camera ${cameraIndex} Details`;
    updateCameraDetailStats(cameraData);
    
    startStopCameraBtn.textContent = cameraData.live_detection_running ? 'Stop Detection' : 'Start Detection';
    
    overlay.style.display = 'block';
    cameraDetailPanel.style.display = 'block';

    startLiveFeed(cameraIndex);
}

function updateCameraDetailStats(cameraData) {
    const isActive = cameraData.live_detection_running === true;
    const lastResult = cameraData.last_result || 'N/A';
    const predictionClass = lastResult === 'success' ? 'prediction-success' : (lastResult === 'failure' ? 'prediction-failure' : '');
    let timeDisplay = 'Never';

    if (cameraData.last_time) {
        const date = new Date(cameraData.last_time * 1000);
        timeDisplay = date.toLocaleTimeString();
    }
    
    let detectionTimesStats = '';
    if (cameraData.detection_times && cameraData.detection_times.length > 0) {
        const avgTime = cameraData.detection_times.reduce((a, b) => a + b, 0) / cameraData.detection_times.length;
        detectionTimesStats = `<p class="camera-stat-item">Average detection time: <span>${avgTime.toFixed(2)}s</span></p>`;
    }

    cameraDetailStats.innerHTML = `
        <p class="camera-stat-item">Status: <span>${isActive ? 'Active' : 'Inactive'}</span></p>
        <p class="camera-stat-item">Last prediction: <span class="${predictionClass}">${lastResult}</span></p>
        <p class="camera-stat-item">Last detection time: <span>${timeDisplay}</span></p>
        ${detectionTimesStats}
    `;
}

function startLiveFeed(cameraIndex) {
    if (liveFeedInterval) {
        clearInterval(liveFeedInterval);
    }
    fetchLiveFeedImage(cameraIndex);
    liveFeedInterval = setInterval(() => {
        fetchLiveFeedImage(cameraIndex);
    }, 1000);
}

function fetchLiveFeedImage(cameraIndex) {
    const currentNotificationImage = document.getElementById('notificationImage');
    if (currentNotificationImage && currentNotificationImage.src && currentNotificationImage.style.display !== 'none') {
        cameraLiveFeedImage.src = currentNotificationImage.src;
        cameraLiveFeedImage.style.display = 'block';
        document.getElementById('cameraLiveFeedPlaceholder').style.display = 'none';
    }
}

function hideCameraDetail() {
    overlay.style.display = 'none';
    cameraDetailPanel.style.display = 'none';
    if (liveFeedInterval) {
        clearInterval(liveFeedInterval);
        liveFeedInterval = null;
    }
    currentCameraIndex = null;
}

function toggleCameraDetection() {
    if (currentCameraIndex === null) return;
    const cameraId = `camera-${currentCameraIndex}`;
    const cameraData = cameraStates[cameraId];
    const isRunning = cameraData.live_detection_running;
    const endpoint = isRunning ? '/live/stop' : '/live/start';
    fetch(endpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ camera_index: currentCameraIndex })
    })
    .then(response => {
        if (response.ok) return response.json();
        throw new Error(`Failed to ${isRunning ? 'stop' : 'start'} detection`);
    })
    .then(data => {
        return fetch('/live/camera', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ camera_index: currentCameraIndex })
        });
    })
    .then(response => response.json())
    .then(data => {
        data.camera_index = currentCameraIndex;
        if (data.live_detection_running === undefined) {
            data.live_detection_running = false;
        }
        updateCameraTile(data);
        updateCameraDetailStats(data);
        startStopCameraBtn.textContent = data.live_detection_running ? 'Stop Detection' : 'Start Detection';
    })
    .catch(error => {
        console.error(`Error toggling camera ${currentCameraIndex} detection:`, error);
    });
}

function cancelPrintFromDetail() {
    if (currentCameraIndex === null) return;
    if (currentAlertId) {
        dismissAlert('cancel_print');
    } else {
        fetch('/alert/cancel_print', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ camera_index: currentCameraIndex })
        })
        .then(response => {
            if (response.ok) {
                console.log('Print cancellation request sent');
            } else {
                console.error('Failed to send print cancellation request');
            }
        })
        .catch(error => console.error('Error:', error));
    }
}

closeCameraDetailBtn.addEventListener('click', hideCameraDetail);
overlay.addEventListener('click', hideCameraDetail);
startStopCameraBtn.addEventListener('click', toggleCameraDetection);
cancelPrintFromDetailBtn.addEventListener('click', cancelPrintFromDetail);
