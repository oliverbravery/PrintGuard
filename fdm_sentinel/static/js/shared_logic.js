const cameraStatsContainer = document.getElementById('cameraStatsContainer');
const cameraStates = {};

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
