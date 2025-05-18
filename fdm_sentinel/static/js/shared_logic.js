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
    if (currentCameraIndex !== null && currentCameraIndex === cameraData.camera_index) {
        updateCameraDetailStats(cameraData);
        startStopCameraBtn.innerHTML = `<span style="pointer-events: none;">${cameraData.live_detection_running ? 'Stop Detection' : 'Start Detection'}</span>`;
    }
});

function formatTimeDisplay(timestamp) {
    if (!timestamp) return 'Never';
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString();
}

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
        let inserted = false;
        const existingTiles = cameraStatsContainer.querySelectorAll('.camera-stats-tile');
        for (const tile of existingTiles) {
            const tileIndex = parseInt(tile.id.split('-')[1]);
            if (cameraIndex < tileIndex) {
                cameraStatsContainer.insertBefore(cameraTile, tile);
                inserted = true;
                break;
            }
        }
        if (!inserted) {
            cameraStatsContainer.appendChild(cameraTile);
        }
    }

    const isActive = cameraData.live_detection_running === true;
    const statusClass = isActive ? 'camera-status-active' : 'camera-status-inactive';
    const lastResult = cameraData.last_result || 'N/A';
    const predictionClass = lastResult === 'success' ? 'prediction-success' : (lastResult === 'failure' ? 'prediction-failure' : '');
    const timeDisplay = formatTimeDisplay(cameraData.last_time);

    cameraTile.innerHTML = `
        <h3 style="pointer-events: none;">
            <span class="camera-status-indicator ${statusClass}" style="pointer-events: none;"></span>
            Camera ${cameraIndex}
        </h3>
        <p class="camera-stats-detail" style="pointer-events: none;">Status: <span style="pointer-events: none;">${isActive ? 'Active' : 'Inactive'}</span></p>
        <p class="camera-stats-detail" style="pointer-events: none;">Last prediction: <span class="${predictionClass}" style="pointer-events: none;">${lastResult}</span></p>
        <p class="camera-stats-detail" style="pointer-events: none;">Last detection: <span style="pointer-events: none;">${timeDisplay}</span></p>
    `;
}

function fetchCameraStates() {
    fetch('/live/available_cameras', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => {
        if (response.ok) return response.json();
        throw new Error('Failed to fetch available cameras');
    })
    .then(data => {
        const cameraIndexes = data.camera_indices;
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
                setTimeout(() => {
                    console.log(`Retrying camera ${index} state...`);
                    fetch('/live/camera', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ camera_index: index })
                    })
                    .then(response => response.json())
                    .then(data => {
                        data.camera_index = index;
                        updateCameraTile(data);
                    })
                    .catch(retryError => console.error(`Retry failed for camera ${index}:`, retryError));
                }, 500);
            });
        });
    })
    .catch(error => {
        console.error('Error fetching available cameras:', error);
        const fallbackIndexes = [0, 1];
        fallbackIndexes.forEach(index => {
            fetch('/live/camera', { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ camera_index: index })
            })
            .then(response => response.ok ? response.json() : Promise.reject('Failed to fetch camera state'))
            .then(data => {
                data.camera_index = index;
                if (data.live_detection_running === undefined) data.live_detection_running = false;
                updateCameraTile(data);
            })
            .catch(err => console.error(`Error fetching camera ${index} state:`, err));
        });
    });
}

setTimeout(() => {
    fetchCameraStates();
    setInterval(fetchCameraStates, 10000);
}, 100);

function showCameraDetail(cameraIndex) {
    currentCameraIndex = cameraIndex;
    const cameraId = `camera-${cameraIndex}`;
    const cameraData = cameraStates[cameraId];
    cameraDetailTitle.textContent = `Camera ${cameraIndex} Details`;
    updateCameraDetailStats(cameraData);
    startStopCameraBtn.innerHTML = `<span style="pointer-events: none;">${cameraData.live_detection_running ? 'Stop Detection' : 'Start Detection'}</span>`;
    overlay.style.display = 'block';
    cameraDetailPanel.style.display = 'block';
    startLiveFeed(cameraIndex);
}

function updateCameraDetailStats(cameraData) {
    const isActive = cameraData.live_detection_running === true;
    const lastResult = cameraData.last_result || 'N/A';
    const predictionClass = lastResult === 'success' ? 'prediction-success' : (lastResult === 'failure' ? 'prediction-failure' : '');
    const timeDisplay = formatTimeDisplay(cameraData.last_time);
    let detectionTimesStats = '';
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
        liveFeedInterval = null;
    }

    cameraLiveFeedImage.onerror = function() {
        console.warn(`Failed to load camera ${cameraIndex} feed, retrying...`);
        setTimeout(() => {
            cameraLiveFeedImage.src = `/camera_feed/${cameraIndex}?t=${Date.now()}`;
        }, 500);
    };
    
    cameraLiveFeedImage.src = `/camera_feed/${cameraIndex}?t=${Date.now()}`;
    cameraLiveFeedImage.style.display = 'block';
    document.getElementById('cameraLiveFeedPlaceholder').style.display = 'none';
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
    .then(responseData => {
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
        updateCameraTile(data);
        updateCameraDetailStats(data);
        startStopCameraBtn.innerHTML = `<span style="pointer-events: none;">${data.live_detection_running ? 'Stop Detection' : 'Start Detection'}</span>`;
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
