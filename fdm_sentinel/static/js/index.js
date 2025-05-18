document.addEventListener('DOMContentLoaded', () => {
    const onboardingComplete = localStorage.getItem('onboardingComplete');
    if (!onboardingComplete) {
        window.location.href = '/onboarding';
        return;
    }

    const camStatusArea = document.getElementById('camStatusArea');
    const camStatusDisplay = document.getElementById('camStatusDisplay');
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    const videoPreview = document.getElementById('videoPreview');
    const cameraSelect = document.getElementById('cameraSelect');

    const elapsedTimeDisplay = document.getElementById('elapsedTimeDisplay');
    const lastResultDisplay = document.getElementById('lastResultDisplay');
    const lastTimeValue = document.getElementById('lastTimeValue');
    const totalDetectionsDisplay = document.getElementById('totalDetectionsDisplay');
    const averageFPSDisplay = document.getElementById('averageFPSDisplay');

    function updateElapsedTime(start_time, doc_element) {
        if (!start_time) {
            doc_element.textContent = '-';
            return;
        }
        const elapsedTime = ((Date.now() / 1000) - start_time).toFixed(0);
        doc_element.textContent = `${elapsedTime}s elapsed`;
    }

    function updateRecentDetectionResult(result, doc_element) {
        doc_element.textContent = result || 'in-active';
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

    function toggleStatusArea(isActive) {
        if (isActive) {
            camStatusArea.classList.remove('status-inactive');
            camStatusArea.classList.add('status-active');
            camStatusDisplay.textContent = 'Detection Active';
        } else {
            camStatusArea.classList.remove('status-active');
            camStatusArea.classList.add('status-inactive');
            camStatusDisplay.textContent = 'Detection Inactive';
        }
    }

    function updatePolledDetectionData(d) {
        updateElapsedTime(d.start_time, elapsedTimeDisplay);
        updateRecentDetectionResult(d.last_result, lastResultDisplay);
        updateRecentDetectionTime(d.last_time, lastTimeValue);
        updateTotalDetectionsCount(d.total_detections, totalDetectionsDisplay);
        updateFrameRate(d.frame_rate, averageFPSDisplay);
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
            toggleStatusArea(data.live_detection_running);
        })
        .catch(error => {
            console.error(`Error fetching metrics for camera ${cameraIdx}:`, error.message);
            const emptyMetrics = {
                start_time: null, last_result: 'Error', last_time: null,
                total_detections: 0, frame_rate: null, live_detection_running: false
            };
            updatePolledDetectionData(emptyMetrics);
            toggleStatusArea(false);
        });
    }

    document.addEventListener('cameraStateUpdated', evt => {
        if (evt.detail && cameraSelect.value && (evt.detail.camera_index == cameraSelect.value)) {
            updatePolledDetectionData(evt.detail);
            if (typeof evt.detail.live_detection_running === 'boolean') {
                toggleStatusArea(evt.detail.live_detection_running);
            }
        }
    });

    cameraSelect.addEventListener('change', () => {
        const selectedCamera = cameraSelect.value;
        if (selectedCamera) {
            videoPreview.src = `/camera_feed/${selectedCamera}?t=${Date.now()}`;
            videoPreview.style.display = 'block';
            fetchAndUpdateMetricsForCamera(selectedCamera);
        }
    });

    startBtn.addEventListener('click', function() {
        const selectedCamera = cameraSelect.value;
        fetch(`/live/start`, { 
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ camera_index: selectedCamera })
        })
            .then(response => {
                if (response.ok) {
                    toggleStatusArea(true);
                } else {
                    console.error('Failed to start live detection');
                }
            })
            .catch(error => console.error('Error:', error));
    });

    stopBtn.addEventListener('click', function() {
        fetch(`/live/stop`, { 
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ camera_index: cameraSelect.value })
        })
            .then(response => {
                if (response.ok) {
                    toggleStatusArea(false);
                } else {
                    console.error('Failed to stop live detection');
                }
            })
            .catch(error => console.error('Error:', error));
    });

    if (videoPreview && cameraSelect) {
        videoPreview.onerror = function() {
            console.warn("Failed to load camera feed, retrying...");
            setTimeout(() => {
                if (cameraSelect.value) {
                    videoPreview.src = `/camera_feed/${cameraSelect.value}?t=${Date.now()}`;
                }
            }, 500);
        };

        setTimeout(() => {
            if (cameraSelect.value) {
                videoPreview.src = `/camera_feed/${cameraSelect.value}?t=${Date.now()}`;
                videoPreview.style.display = 'block';
                fetchAndUpdateMetricsForCamera(cameraSelect.value);
            } else {
                console.warn("No camera selected initially or camera select is empty.");
                const emptyMetrics = {
                    start_time: null, last_result: 'N/A', last_time: null,
                    total_detections: 0, frame_rate: null, live_detection_running: false
                };
                updatePolledDetectionData(emptyMetrics);
                toggleStatusArea(false);
                videoPreview.style.display = 'none';
            }
        }, 100);
    }
});