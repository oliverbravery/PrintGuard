import { registerPush, unsubscribeFromPush } from './notifications.js';
import { render_ascii_title } from './utils.js';

const asciiTitle = document.getElementById('ascii-title');
const cameraTitle = document.getElementById('cameraTitle');
const camPredictionDisplay = document.getElementById('camPredictionDisplay');
const camPredictionTimeDisplay = document.getElementById('camPredictionTimeDisplay');
const camTotalDetectionsDisplay = document.getElementById('camTotalDetectionsDisplay');
const camFrameRateDisplay = document.getElementById('camFrameRateDisplay');
const camDetectionToggleButton = document.getElementById('camDetectionToggleButton');
const camDetectionLiveIndicator = document.getElementsByClassName('live-indicator');
const camVideoPreview = document.getElementById('videoPreview');
const loadingOverlay = document.getElementById('loadingOverlay');
const cameraItems = document.querySelectorAll('.camera-item');
const settingsButton = document.getElementById('settingsButton');
const cameraDisplaySection = document.querySelector('.camera-display-section');
const settingsSection = document.querySelector('.settings-section');
const notificationsBtn = document.getElementById('notificationBtn');

const settingsCameraUUID = document.getElementById('camera_uuid');
const settingsSensitivity = document.getElementById('sensitivity');
const settingsSensitivityLabel = document.getElementById('sensitivity_val');
const settingsBrightness = document.getElementById('brightness');
const settingsBrightnessLabel = document.getElementById('brightness_val');
const settingsContrast = document.getElementById('contrast');
const settingsContrastLabel = document.getElementById('contrast_val');
const settingsFocus = document.getElementById('focus');
const settingsFocusLabel = document.getElementById('focus_val');
const settingsCountdownTime = document.getElementById('countdown_time');
const settingsCountdownTimeLabel = document.getElementById('countdown_time_val');
const settingsMajorityVoteThreshold = document.getElementById('majority_vote_threshold');
const settingsMajorityVoteThresholdLabel = document.getElementById('majority_vote_threshold_val');
const settingsMajorityVoteWindow = document.getElementById('majority_vote_window');
const settingsMajorityVoteWindowLabel = document.getElementById('majority_vote_window_val');
const settingsCountdownAction = document.getElementById('countdown_action');

const addCameraModalOverlay = document.getElementById('addCameraModalOverlay');
const addCameraModalClose = document.getElementById('addCameraModalClose');
const addCameraBtn = document.getElementById('addCameraBtn');
const addFirstCameraBtn = document.getElementById('addFirstCameraBtn');

camVideoPreview.onload = () => {
    loadingOverlay.style.display = 'none';
};

camVideoPreview.onerror = () => {
    loadingOverlay.style.display = 'none';
    console.error("Failed to load camera feed.");
};

const stopDetectionBtnLabel = 'Stop Detection';
const startDetectionBtnLabel = 'Start Detection';

let cameraUUID = 0;
let currentCameraPrinterConfig = null;

function changeLiveCameraFeed(cameraUUID) {
    loadingOverlay.style.display = 'flex';
    camVideoPreview.src = `/camera/feed/${cameraUUID}`;
}

function updateCameraTitle(nickname) {
    const titleText = nickname ? nickname : 'No camera selected';
    cameraTitle.textContent = titleText;
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
        camDetectionLiveIndicator[0].textContent = `active`;
        camDetectionLiveIndicator[0].style.color = '#2ecc40';
    } else {
        camDetectionLiveIndicator[0].textContent = `inactive`;
        camDetectionLiveIndicator[0].style.color = '#b2b2b2';
    }
}

function updateDetectionButton(isActive) {
    if (isActive) {
        camDetectionToggleButton.textContent = stopDetectionBtnLabel;
    } else {
        camDetectionToggleButton.textContent = startDetectionBtnLabel;
    }
}

function updateSelectedCameraSettings(d) {
    settingsCameraUUID.value = d.camera_uuid;
    settingsSensitivityLabel.textContent = d.sensitivity;
    settingsSensitivity.value = d.sensitivity;
    updateSliderFill(settingsSensitivity);
    settingsBrightnessLabel.textContent = d.brightness;
    settingsBrightness.value = d.brightness;
    updateSliderFill(settingsBrightness);
    settingsContrastLabel.textContent = d.contrast;
    settingsContrast.value = d.contrast;
    updateSliderFill(settingsContrast);
    settingsFocusLabel.textContent = d.focus;
    settingsFocus.value = d.focus;
    updateSliderFill(settingsFocus);
    settingsCountdownTimeLabel.textContent = d.countdown_time;
    settingsCountdownTime.value = d.countdown_time;
    updateSliderFill(settingsCountdownTime);
    settingsMajorityVoteThresholdLabel.textContent = d.majority_vote_threshold;
    settingsMajorityVoteThreshold.value = d.majority_vote_threshold;
    updateSliderFill(settingsMajorityVoteThreshold);
    settingsMajorityVoteWindowLabel.textContent = d.majority_vote_window;
    settingsMajorityVoteWindow.value = d.majority_vote_window;
    updateSliderFill(settingsMajorityVoteWindow);
    settingsCountdownAction.value = d.countdown_action;
    currentCameraPrinterConfig = d.printer_config;

    const hasPrinter = d.printer_id !== null && d.printer_id !== undefined;
    for (const option of settingsCountdownAction.options) {
        if (option.value === 'cancel_print' || option.value === 'pause_print') {
            option.disabled = !hasPrinter;
        }
    }
    if (!hasPrinter && (settingsCountdownAction.value === 'cancel_print' || settingsCountdownAction.value === 'pause_print')) {
        settingsCountdownAction.value = 'dismiss';
        saveSetting(settingsCountdownAction);
    }
}

function printerTileStyle(linked) {
    const printerConfigBtn = document.getElementById('printerConfigBtn');
    const linkPrinterBtn = document.getElementById('linkPrinterBtn');
    const printerConfigStatus = document.getElementById('printerConfigStatus');
    if (linked) {
        printerConfigBtn.style.display = 'block';
        linkPrinterBtn.style.display = 'none';
        printerConfigStatus.textContent = `Printer Settings`;
    } else {
        printerConfigBtn.style.display = 'none';
        linkPrinterBtn.style.display = 'block';
    }
}

function updateSelectedCamerasPrinterModal(printerStatus, printerTemperature, printerBedTemperature) {
    const printerStatusLbl = document.getElementById('modalPrinterStatus');
    const printerTemperatureLbl = document.getElementById('modalNozzleTemp');
    const printerBedTemperatureLbl = document.getElementById('modalBedTemp');
    const hasPrinter = currentCameraPrinterConfig !== null && currentCameraPrinterConfig !== undefined;
    printerTileStyle(hasPrinter);
    if (hasPrinter) {
        printerStatusLbl.textContent = printerStatus;
        printerTemperatureLbl.textContent = printerTemperature;
        printerBedTemperatureLbl.textContent = printerBedTemperature;
    }
}

function updateSelectedCameraData(d) {
    updateRecentDetectionResult(d.last_result, camPredictionDisplay);
    updateRecentDetectionTime(d.last_time, camPredictionTimeDisplay);
    updateTotalDetectionsCount(d.total_detections, camTotalDetectionsDisplay);
    updateFrameRate(d.frame_rate, camFrameRateDisplay);
    toggleIsDetectingStatus(d.live_detection_running);
    updateDetectionButton(d.live_detection_running);
    printerTileStyle(d.printer_id !== undefined && d.printer_id !== null);
}

function updateCameraSelectionListData(d) {
    cameraItems.forEach(item => {
        const cameraId = item.dataset.cameraId;

        if (cameraId == d.camera_uuid) {
            item.querySelector('.camera-prediction').textContent = d.last_result;
            item.querySelector('#lastTimeValue').textContent = d.last_time ? new Date(d.last_time * 1000).toLocaleTimeString() : '-';
            item.querySelector('.camera-prediction').style.color = d.last_result === 'success' ? 'green' : 'red';
            let statusIndicator = item.querySelector('.camera-status');
            if (d.live_detection_running) {
                statusIndicator.textContent = `active`;
                statusIndicator.style.color = '#2ecc40';
                statusIndicator.style.backgroundColor = 'transparent';
            } else {
                statusIndicator.textContent = `inactive`;
                statusIndicator.style.color = '#b2b2b2';
                statusIndicator.style.backgroundColor = 'transparent';
            }
            item.querySelector('#cameraPreview').src = `/camera/feed/${d.camera_uuid}`;
        }
    });
}

function removeCamera(cameraUUID) {
    if (!cameraUUID) {
        console.warn('Cannot remove camera: invalid camera UUID provided.');
        return;
    }
    if (!confirm('Are you sure you want to remove this camera?')) {
        return;
    }
    fetch('/camera/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_uuid: cameraUUID })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(`Failed to remove camera ${cameraUUID}: ${errData.detail || response.statusText}`);
            });
        }
        return response.json();
    })
    .then(() => {
        const cameraItem = document.querySelector(`.camera-item[data-camera-id="${cameraUUID}"]`);
        if (cameraItem) {
            cameraItem.remove();
        }
        if (window.cameraUUID === cameraUUID) {
            const firstCamera = document.querySelector('.camera-item');
            if (firstCamera) {
                firstCamera.click();
            } else {
                window.location.reload();
            }
        }
        const remainingCameras = document.querySelectorAll('.camera-item');
        if (remainingCameras.length === 0) {
            if (addCameraModalOverlay) {
                addCameraModalOverlay.style.display = 'flex';
            }
        }
    })
    .catch(error => {
        console.error(`Error removing camera ${cameraUUID}:`, error.message);
        alert(`Failed to remove camera: ${error.message}`);
    });
}

function updatePolledDetectionData(d) {
    if ('camera_uuid' in d && d.camera_uuid == cameraUUID) {
        updateSelectedCameraData(d);
    }
    updateCameraSelectionListData(d);
}

function updatePolledPrinterData(d) {
    const nozzleTemp = d.temperatureReading?.nozzle_actual || 0;
    const bedTemp = d.temperatureReading?.bed_actual || 0;
    const jobState = d.jobInfoResponse?.state || 'Unknown';
    updateSelectedCamerasPrinterModal(
        jobState,
        nozzleTemp,
        bedTemp
    );
}

function fetchAndUpdateMetricsForCamera(cameraUUID) {
    if (!cameraUUID) {
        console.warn('Cannot fetch metrics: invalid camera UUID provided:', cameraUUID);
        return;
    }
    fetch(`/camera/state`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_uuid: cameraUUID })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(`Failed to fetch camera state for camera ${cameraUUID}: ${errData.detail || response.statusText}`);
            }).catch(() => {
                throw new Error(`Failed to fetch camera state for camera ${cameraUUID}: ${response.statusText}`);
            });
        }
        return response.json();
    })
    .then(data => {
        const metricsData = {
            camera_uuid: cameraUUID,
            start_time: data.start_time,
            last_result: data.last_result,
            last_time: data.last_time,
            total_detections: data.detection_times ? data.detection_times.length : 0,
            frame_rate: data.frame_rate,
            live_detection_running: data.live_detection_running,
            brightness: data.brightness,
            contrast: data.contrast,
            focus: data.focus,
            sensitivity: data.sensitivity,
            countdown_time: data.countdown_time,
            majority_vote_threshold: data.majority_vote_threshold,
            majority_vote_window: data.majority_vote_window,
            printer_id: data.printer_id,
            printer_config: data.printer_config,
            countdown_action: data.countdown_action
        };
        updatePolledDetectionData(metricsData);
        updateSelectedCameraSettings(metricsData);
    })
    .catch(error => {
        console.error(`Error fetching metrics for camera ${cameraUUID}:`, error.message);
        const emptyMetrics = {
            camera_uuid: cameraUUID,
            start_time: null,
            last_result: '-',
            last_time: null,
            total_detections: 0,
            frame_rate: null,
            live_detection_running: false
        };
        updatePolledDetectionData(emptyMetrics);
    });
}

function sendDetectionRequest(isStart) {
    if (cameraUUID === null || cameraUUID === undefined) {
        console.warn(`Cannot ${isStart ? 'start' : 'stop'} detection: no valid camera selected`);
        return;
    }
    fetch(`/detect/live/${isStart ? 'start' : 'stop'}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ camera_uuid: cameraUUID })
    })
    .then(response => {
        if (response.ok) {
            fetchAndUpdateMetricsForCamera(cameraUUID);
        } else {
            response.json().then(errData => {
                console.error(`Failed to ${isStart ? 'start' : 'stop'} live detection for camera ${cameraUUID}. Server: ${errData.detail || response.statusText}`);
            }).catch(() => {
                console.error(`Failed to ${isStart ? 'start' : 'stop'} live detection for camera ${cameraUUID}. Status: ${response.status} ${response.statusText}`);
            });
        }
    })
    .catch(error => {
        console.error(`Network error or exception during ${isStart ? 'start' : 'stop'} request for camera ${cameraUUID}:`, error);
    });
}

camDetectionToggleButton.addEventListener('click', function() {
    if (camDetectionToggleButton.textContent === startDetectionBtnLabel) {
        camDetectionToggleButton.textContent = stopDetectionBtnLabel;
        sendDetectionRequest(true);
        toggleIsDetectingStatus(true);
    } else {
        camDetectionToggleButton.textContent = startDetectionBtnLabel;
        sendDetectionRequest(false);
        toggleIsDetectingStatus(false);
    }
});

render_ascii_title(asciiTitle, 'PrintGuard');

cameraItems.forEach(item => {
    item.addEventListener('click', function() {
        cameraItems.forEach(i => i.classList.remove('selected'));
        this.classList.add('selected');
        const cameraId = this.dataset.cameraId;
        if (cameraId) {
            const nickname = this.querySelector('.camera-header span:first-child').textContent;
            changeLiveCameraFeed(cameraId);
            cameraUUID = cameraId;
            settingsCameraUUID.value = cameraId;
            updateCameraTitle(nickname);
            stopPrinterStatusPolling();
            fetchAndUpdateMetricsForCamera(cameraId);
        } else {
            cameraUUID = null;
            settingsCameraUUID.value = '';
            updateCameraTitle(null);
        }
    });

    const removeButton = item.querySelector('.remove-camera-btn');
    removeButton.addEventListener('click', function(event) {
        event.stopPropagation();
        const cameraId = item.dataset.cameraId;
        removeCamera(cameraId);
    });
});

document.addEventListener('cameraStateUpdated', evt => {
    if (evt.detail) {
        updatePolledDetectionData(evt.detail);
    }
});

document.addEventListener('printerStateUpdated', evt => {
    if (evt.detail) {
        updatePolledPrinterData(evt.detail);
    }
});

document.addEventListener('DOMContentLoaded', function() {
    const firstCameraItem = cameraItems[0];
    if (firstCameraItem) {
        const cameraId = firstCameraItem.dataset.cameraId;
        if (cameraId) {
            firstCameraItem.click();
        } else {
            if (addCameraModalOverlay) {
                addCameraModalOverlay.style.display = 'flex';
            }
        }
    } else {
        const noCamerasMessage = document.getElementById('noCamerasMessage');
        if (noCamerasMessage && addCameraModalOverlay) {
            addCameraModalOverlay.style.display = 'flex';
        }
    }
});

addCameraBtn?.addEventListener('click', function(e) {
    e.preventDefault();
    addCameraModalOverlay.style.display = 'flex';
});

addFirstCameraBtn?.addEventListener('click', function(e) {
    e.preventDefault();
    addCameraModalOverlay.style.display = 'flex';
});

let isSettingsVisible = false;

settingsButton.addEventListener('click', function() {
    isSettingsVisible = !isSettingsVisible;
    
    if (isSettingsVisible) {
        cameraDisplaySection.style.display = 'none';
        settingsSection.style.display = 'block';
        render_ascii_title(asciiTitle, 'Settings');
        settingsButton.textContent = 'Back';
    } else {
        cameraDisplaySection.style.display = 'block';
        settingsSection.style.display = 'none';
        updateAsciiTitle();
        settingsButton.textContent = 'Settings';
    }
});

let notificationsEnabled = false;
notificationsBtn.textContent = '';

async function checkNotificationsEnabled() {
    if (!('Notification' in window)) {
        return false;
    }
    if (Notification.permission !== 'granted') {
        return false;
    }
    try {
        const resp = await fetch('/notification/debug');
        if (resp.ok) {
            const data = await resp.json();
            return data.subscriptions_count > 0;
        } else {
            console.error('Failed to fetch notification status from server:', resp.status);
            return false;
        }
    } catch (error) {
        console.error('Error checking notification status:', error);
        return false;
    }
}

async function updateNotificationButtonState() {
    notificationsEnabled = await checkNotificationsEnabled();
    
    if (notificationsEnabled) {
        notificationsBtn.classList.remove('disabled');
        notificationsBtn.classList.add('enabled');
        console.debug('Notifications are enabled, button set to ON state');
    } else {
        notificationsBtn.classList.remove('enabled');
        notificationsBtn.classList.add('disabled');
        console.debug('Notifications are disabled, button set to OFF state');
    }
    notificationsBtn.textContent = '';
}

updateNotificationButtonState();

notificationsBtn.addEventListener('click', async () => {
    notificationsBtn.disabled = true;
    try {
        if (await checkNotificationsEnabled()) {
            console.debug('Unsubscribing from notifications...');
            await unsubscribeFromPush();
            try {
                const res = await fetch('/notification/unsubscribe', {method: 'POST'});
                if (!res.ok) console.error('Server unsubscribe failed:', res.status);
            } catch (err) {
                console.error('Error during server unsubscribe:', err);
            }
        } else {
            console.debug('Subscribing to notifications...');
            await registerPush();
        }
        setTimeout(() => {
            updateNotificationButtonState();
            notificationsBtn.disabled = false;
        }, 500);
    } catch (error) {
        console.error('Failed to toggle notifications:', error);
        notificationsBtn.disabled = false;
    }
});

function updateSliderFill(slider) {
    const min = slider.min || 0;
    const max = slider.max || 100;
    const value = slider.value;
    const percentage = ((value - min) / (max - min)) * 100;
    slider.style.setProperty('--value', `${percentage}%`);
    const valueSpan = document.getElementById(`${slider.id}_val`);
    if (valueSpan) {
        valueSpan.textContent = value;
    }
}

function saveSetting(slider) {
    const settingsForm = slider.closest('form');
    if (!settingsForm) return;
    const formData = new FormData(settingsForm);
    const setting = slider.name;
    const value = slider.value;
    fetch(settingsForm.action, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams(formData)
    })
    .then(response => {
        if (response.ok) {
            const valueSpan = document.getElementById(`${slider.id}_val`);
            if (valueSpan) {
                valueSpan.textContent = value;
            }
        } else {
            console.error(`Failed to update setting ${setting}`);
        }
    })
    .catch(error => {
        console.error(`Error saving setting ${setting}:`, error);
    });
}

document.querySelectorAll('.settings-form input[type="range"]').forEach(slider => {
    updateSliderFill(slider);
    slider.addEventListener('input', () => {
        updateSliderFill(slider);
    });
    slider.addEventListener('change', (e) => {
        e.preventDefault();
        updateSliderFill(slider);
        saveSetting(slider);
    });
});

document.getElementById('countdown_action').addEventListener('change', (e) => {
    saveSetting(e.target);
});

document.querySelector('.settings-form')?.addEventListener('submit', (e) => {
    e.preventDefault();
});

function isMobileView() {
    return window.innerWidth <= 768;
}

function isSmallMobileView() {
    return window.innerWidth <= 380;
}

function updateAsciiTitle() {
    if (isSettingsVisible) {
        render_ascii_title(asciiTitle, 'Settings');
    } else {
        const title = 'PrintGuard';
        render_ascii_title(asciiTitle, title);

        if (isMobileView()) {
            asciiTitle.style.marginTop = '80px';
            asciiTitle.style.transformOrigin = 'center center';
            asciiTitle.style.transform = 'scale(0.35)';
        } else if (isSmallMobileView()) {
            asciiTitle.style.marginTop = '60px';
            asciiTitle.style.transformOrigin = 'center';
            asciiTitle.style.transform = 'scale(0.3)';
        }
        else {
            asciiTitle.style.marginTop = '';
            asciiTitle.style.transformOrigin = 'center';
            asciiTitle.style.transform = 'scale(0.8)';
        }
    }
}

updateAsciiTitle();

window.addEventListener('resize', updateAsciiTitle);

const configureSetupBtn = document.getElementById('configureSetupBtn');
const setupModalOverlay = document.getElementById('setupModalOverlay');
const setupModalClose = document.getElementById('setupModalClose');

configureSetupBtn?.addEventListener('click', function(e) {
    e.preventDefault();
    setupModalOverlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    setTimeout(() => {
        initializeFeedSettings();
    }, 100);
});

const goToSetupBtn = document.getElementById('goToSetupBtn');
goToSetupBtn?.addEventListener('click', function() {
    window.location.href = '/setup';
});

function updateFeedSliderFill(slider) {
    const min = slider.min || 0;
    const max = slider.max || 100;
    const value = slider.value;
    const percentage = ((value - min) / (max - min)) * 100;
    slider.style.setProperty('--value', `${percentage}%`);
    const valueSpan = document.getElementById(`${slider.id}_val`);
    if (valueSpan) {
        valueSpan.textContent = value;
    }
}

function saveFeedSetting(slider) {
    const setting = slider.name;
    const value = parseInt(slider.value);
    const valueSpan = document.getElementById(`${slider.id}_val`);
    if (valueSpan) {
        valueSpan.textContent = value;
    }
    if (setting === 'detectionInterval') {
        const detectionsPerSecond = Math.round(1000 / value);
        const dpsSlider = document.getElementById('detectionsPerSecond');
        const dpsSpan = document.getElementById('detectionsPerSecond_val');
        if (dpsSlider && dpsSpan) {
            dpsSlider.value = detectionsPerSecond;
            dpsSpan.textContent = detectionsPerSecond;
            updateFeedSliderFill(dpsSlider);
        }
    } else if (setting === 'detectionsPerSecond') {
        const detectionInterval = Math.round(1000 / value);
        const diSlider = document.getElementById('detectionInterval');
        const diSpan = document.getElementById('detectionInterval_val');
        if (diSlider && diSpan) {
            diSlider.value = detectionInterval;
            diSpan.textContent = detectionInterval;
            updateFeedSliderFill(diSlider);
        }
    }
    saveFeedSettings();
}

function saveFeedSettings() {
    const settings = {
        stream_max_fps: parseInt(document.getElementById('streamMaxFps').value),
        stream_tunnel_fps: parseInt(document.getElementById('streamTunnelFps').value),
        stream_jpeg_quality: parseInt(document.getElementById('streamJpegQuality').value),
        stream_max_width: parseInt(document.getElementById('streamMaxWidth').value),
        detections_per_second: parseInt(document.getElementById('detectionsPerSecond').value),
        detection_interval_ms: parseInt(document.getElementById('detectionInterval').value),
        printer_stat_polling_rate_ms: parseInt(document.getElementById('printerStatPollingRate').value),
        min_sse_dispatch_delay_ms: parseInt(document.getElementById('minSseDispatchDelay').value)
    };
    fetch('/save-feed-settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings)
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(errData.detail || 'Failed to save feed settings');
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('Feed settings saved successfully:', data);
    })
    .catch(error => {
        console.error('Error saving feed settings:', error);
    });
}

function initializeFeedSettings() {
    loadFeedSettings().then(() => {
        document.querySelectorAll('.feed-setting-item input[type="range"]').forEach(slider => {
            updateFeedSliderFill(slider);
            slider.addEventListener('input', () => {
                updateFeedSliderFill(slider);
            });
            slider.addEventListener('change', (e) => {
                e.preventDefault();
                updateFeedSliderFill(slider);
                saveFeedSetting(slider);
            });
        });
    });
}

function loadFeedSettings() {
    return fetch('/get-feed-settings', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(errData.detail || 'Failed to load feed settings');
            });
        }
        return response.json();
    })
    .then(data => {
        if (data.success && data.settings) {
            const settings = data.settings;
            updateSliderValue('streamMaxFps', settings.stream_max_fps);
            updateSliderValue('streamTunnelFps', settings.stream_tunnel_fps);
            updateSliderValue('streamJpegQuality', settings.stream_jpeg_quality);
            updateSliderValue('streamMaxWidth', settings.stream_max_width);
            updateSliderValue('detectionsPerSecond', settings.detections_per_second);
            updateSliderValue('detectionInterval', settings.detection_interval_ms);
            updateSliderValue('printerStatPollingRate', settings.printer_stat_polling_rate_ms);
            updateSliderValue('minSseDispatchDelay', settings.min_sse_dispatch_delay_ms);
        }
    })
    .catch(error => {
        console.error('Error loading feed settings:', error);
    });
}

function updateSliderValue(sliderId, value) {
    const slider = document.getElementById(sliderId);
    const valueSpan = document.getElementById(`${sliderId}_val`);
    if (slider && valueSpan) {
        slider.value = value;
        valueSpan.textContent = value;
        updateFeedSliderFill(slider);
    }
}

setupModalClose?.addEventListener('click', function() {
    setupModalOverlay.style.display = 'none';
    document.body.style.overflow = '';
});

function unlinkPrinter() {
    const camUUID = settingsCameraUUID.value;
    if (!camUUID) return;
    if (confirm('Are you sure you want to unlink this printer from the camera?')) {
        stopPrinterStatusPolling();
        fetch(`/printer/remove/${camUUID}`, {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                fetchAndUpdateMetricsForCamera(camIdx);
                alert('Printer unlinked successfully');
            } else {
                alert('Failed to unlink printer: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Error unlinking printer:', error);
            alert('Error unlinking printer');
        });
    }
}

document.getElementById('linkPrinterBtn')?.addEventListener('click', openPrinterModal);
document.getElementById('printerConfigBtn')?.addEventListener('click', openPrinterModal);

const printerModalOverlay = document.getElementById('printerModalOverlay');
const printerModalClose = document.getElementById('printerModalClose');

function openPrinterModal() {
    const cameraUUID = settingsCameraUUID.value;
    fetch ('/sse/start-polling', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({camera_uuid: cameraUUID})
    });
    if (cameraUUID !== undefined && cameraUUID !== null) {
        settingsCameraUUID.value = cameraUUID;
    }
    fetch(`/camera/state`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_uuid: cameraUUID })
    })
    .then(res => {
        if (!res.ok) {
            return res.json().then(errData => {
                throw new Error(`Failed to fetch camera state for camera ${cameraUUID}: ${errData.detail || res.statusText}`);
            });
        }
        return res.json();
    })
    .then(data => {
        const formDiv = document.getElementById('modalNoPrinterForm');
        const modalInfo = document.getElementById('modalPrinterInfo');
        if (data.printer_config) {
            formDiv.style.display = 'none';
            modalInfo.style.display = 'block';
            document.getElementById('modalPrinterName').textContent = data.printer_config.name;
            document.getElementById('modalPrinterType').textContent = data.printer_config.printer_type + ' | ' + data.printer_config.base_url;
        } else {
            modalInfo.style.display = 'none';
            formDiv.style.display = 'block';
        }
        printerModalOverlay.style.display = 'flex';
    })
    .catch(error => {
        console.error('Error opening printer modal:', error);
        alert('Error loading printer information: ' + error.message);
    });
}

window.openPrinterModal = openPrinterModal;

printerModalClose.addEventListener('click', () => {
    printerModalOverlay.style.display = 'none';
    stopPrinterStatusPolling();
});

function stopPrinterStatusPolling() {
    const cameraUUID = settingsCameraUUID.value;
    if (cameraUUID !== null && cameraUUID !== undefined) {
        fetch('/sse/stop-polling', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({camera_uuid: cameraUUID})
        });
    }
}

document.getElementById('modalCancelPrintBtn').addEventListener('click', () => {
    const cameraUUID = settingsCameraUUID.value;
    fetch(`/printer/cancel/${cameraUUID}`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({})
    }).then(response => {
        if (response.ok) {
            alert('Print cancelled successfully');
        } else {
            return response.json().then(errData => {
                console.error('Error cancelling print:', errData);
            });
        }
    });
});

document.getElementById('modalPausePrintBtn').addEventListener('click', () => {
    const cameraUUID = settingsCameraUUID.value;
    fetch(`/printer/pause/${cameraUUID}`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({})
    }).then(response => {
        if (response.ok) {
            alert('Print paused successfully');
        } else {
            return response.json().then(errData => {
                console.error('Error pausing print:', errData);
            });
        }
    });
});

document.getElementById('modalUnlinkPrinterBtn').addEventListener('click', () => {
    unlinkPrinter();
    printerModalOverlay.style.display = 'none';
});

document.getElementById('modalPrinterConnectionType').addEventListener('change', (e) => {
    document.getElementById('modalOctoprintConfig').style.display = e.target.value === 'octoprint' ? 'block' : 'none';
});

document.getElementById('linkPrinterForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const submitButton = e.target.querySelector('button[type="submit"]');
    const originalButtonText = submitButton.textContent;
    const printerType = document.getElementById('modalPrinterConnectionType').value.trim();
    const printerName = document.getElementById('modalPrinterNameInput').value.trim();
    const baseUrl = document.getElementById('modalOctoprintUrlInput').value.trim();
    const apiKey = document.getElementById('modalOctoprintApiKeyInput').value.trim();

    if (!printerType) {
        alert('Please select a connection type');
        return;
    }
    if (!printerName) {
        alert('Please enter a printer name');
        return;
    }
    if (printerType === 'octoprint') {
        if (!baseUrl) {
            alert('Please enter the base URL');
            return;
        }
        if (!apiKey) {
            alert('Please enter the API key');
            return;
        }
    }

    submitButton.disabled = true;
    submitButton.textContent = 'Linking...';
    const cameraUUID = settingsCameraUUID.value;
    const body = {
        printer_type: printerType,
        name: printerName,
        base_url: baseUrl,
        api_key: apiKey,
        camera_uuid: cameraUUID
    };
    try {
        const res = await fetch(`/printer/add/${cameraUUID}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        
        if (data.success) {
            console.log('Printer linked successfully, updating UI...');
            await fetchAndUpdateMetricsForCamera(camIdx);
            printerModalOverlay.style.display = 'none';
            document.getElementById('linkPrinterForm').reset();
            document.getElementById('modalOctoprintConfig').style.display = 'none';
            alert('Printer linked successfully!');
            setTimeout(() => {
                console.log('Reopening modal to show printer info...');
                openPrinterModal();
            }, 200);
        } else {
            console.error('Failed to link printer:', data.error);
            alert('Failed to link printer: ' + (data.error || 'unknown'));
        }
    } catch (error) {
        console.error('Error linking printer:', error);
        alert('Error linking printer. Please check your connection and try again.');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = originalButtonText;
    }
});

addCameraModalClose?.addEventListener('click', function() {
    if (addCameraModalOverlay) {
        addCameraModalOverlay.style.display = 'none';
    }
});

addCameraModalOverlay?.addEventListener('click', function(e) {
    if (e.target === addCameraModalOverlay) {
        addCameraModalOverlay.style.display = 'none';
    }
});

const addSerialCameraButton = document.getElementById('addSerialCameraButton');
const addRtspCameraButton = document.getElementById('addRtspCameraButton');
const cameraTypeSelection = document.getElementById('cameraTypeSelection');
const addCameraForm = document.getElementById('addCameraForm');
const serialCameraSetup = document.getElementById('serialCameraSetup');
const rtspCameraSetup = document.getElementById('rtspCameraSetup');
const serialDeviceSelect = document.getElementById('serialDevice');
const rtspUrlInput = document.getElementById('rtspUrl');
const serialLoading = document.getElementById('serialLoading');
const noSerialDeviceMessage = document.getElementById('noSerialDeviceMessage');

const enablePreview = document.getElementById('enablePreview');
const cameraPreviewContainer = document.getElementById('cameraPreviewContainer');
const cameraPreviewImage = document.getElementById('cameraPreviewImage');
const cameraPreviewLoading = document.getElementById('cameraPreviewLoading');
const cameraPreviewError = document.getElementById('cameraPreviewError');

let previewUpdateTimeout;

function showPreviewLoading() {
    cameraPreviewImage.style.display = 'none';
    cameraPreviewError.style.display = 'none';
    cameraPreviewLoading.style.display = 'flex';
}

function showPreviewError() {
    cameraPreviewImage.style.display = 'none';
    cameraPreviewLoading.style.display = 'none';
    cameraPreviewError.style.display = 'flex';
}

function showPreviewImage(src) {
    cameraPreviewLoading.style.display = 'none';
    cameraPreviewError.style.display = 'none';
    cameraPreviewImage.src = src;
    cameraPreviewImage.style.display = 'block';
}

function hidePreview() {
    cameraPreviewContainer.style.display = 'none';
    cameraPreviewImage.style.display = 'none';
    cameraPreviewLoading.style.display = 'none';
    cameraPreviewError.style.display = 'none';
}

function updatePreview() {
    if (!enablePreview.checked) {
        hidePreview();
        return;
    }
    
    cameraPreviewContainer.style.display = 'block';
    let source = '';
    if (serialCameraSetup.style.display !== 'none' && serialDeviceSelect.value) {
        source = serialDeviceSelect.value;
    } else if (rtspCameraSetup.style.display !== 'none' && rtspUrlInput.value) {
        source = rtspUrlInput.value;
    }
    if (!source) {
        showPreviewError();
        return;
    }
    showPreviewLoading();
    const previewUrl = `/camera/preview?source=${encodeURIComponent(source)}`;
    const img = new Image();
    img.onload = function() {
        showPreviewImage(previewUrl);
    };
    img.onerror = function() {
        showPreviewError();
    };
    img.src = previewUrl;
}

function schedulePreviewUpdate() {
    if (previewUpdateTimeout) {
        clearTimeout(previewUpdateTimeout);
    }
    previewUpdateTimeout = setTimeout(updatePreview, 1000);
}

addSerialCameraButton?.addEventListener('click', async () => {
    cameraTypeSelection.style.display = 'none';
    addCameraForm.style.display = 'block';
    serialCameraSetup.style.display = 'block';
    rtspCameraSetup.style.display = 'none';
    rtspUrlInput.required = false;
    serialDeviceSelect.required = true;
    serialLoading.style.display = 'block';
    serialDeviceSelect.style.display = 'none';
    noSerialDeviceMessage.style.display = 'none';

    try {
        const response = await fetch('/camera/serial_devices');
        const devices = await response.json();
        serialDeviceSelect.innerHTML = '';
        if (devices.length > 0) {
            const defaultOption = document.createElement('option');
            defaultOption.value = '';
            defaultOption.textContent = 'Select a serial device';
            defaultOption.disabled = true;
            defaultOption.selected = true;
            serialDeviceSelect.appendChild(defaultOption);
            
            devices.forEach(device => {
                const option = document.createElement('option');
                option.value = device;
                option.textContent = device;
                serialDeviceSelect.appendChild(option);
            });
            serialDeviceSelect.style.display = 'block';
            serialDeviceSelect.selectedIndex = 0;
            const changeEvent = new Event('change', { bubbles: true });
            serialDeviceSelect.dispatchEvent(changeEvent);
        } else {
            noSerialDeviceMessage.style.display = 'block';
            serialDeviceSelect.required = false;
        }
    } catch (error) {
        console.error('Error fetching serial devices:', error);
        noSerialDeviceMessage.textContent = 'Error fetching devices.';
        noSerialDeviceMessage.style.display = 'block';
    } finally {
        serialLoading.style.display = 'none';
    }
});

addRtspCameraButton?.addEventListener('click', () => {
    cameraTypeSelection.style.display = 'none';
    addCameraForm.style.display = 'block';
    serialCameraSetup.style.display = 'none';
    rtspCameraSetup.style.display = 'block';
    serialDeviceSelect.required = false;
    rtspUrlInput.required = true;
});

enablePreview?.addEventListener('change', updatePreview);

serialDeviceSelect?.addEventListener('change', () => {
    if (enablePreview.checked) {
        updatePreview();
    }
});

rtspUrlInput?.addEventListener('input', () => {
    if (enablePreview.checked) {
        schedulePreviewUpdate();
    }
});

addCameraForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(addCameraForm);
    const data = {};
    formData.forEach((value, key) => {
        if (value) {
            data[key] = value;
        }
    });

    try {
        const response = await fetch('/camera/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data),
        });

        if (response.ok) {
            addCameraModalOverlay.style.display = 'none';
            addCameraForm.reset();
            addCameraForm.style.display = 'none';
            cameraTypeSelection.style.display = 'flex';
            location.reload();
        } else {
            const errorData = await response.json();
            alert(`Error: ${errorData.detail}`);
        }
    } catch (error) {
        console.error('Error adding camera:', error);
        alert('An error occurred while adding the camera.');
    }
});

addCameraModalClose?.addEventListener('click', function() {
    addCameraModalOverlay.style.display = 'none';
    addCameraForm.reset();
    addCameraForm.style.display = 'none';
    cameraTypeSelection.style.display = 'flex';
    serialCameraSetup.style.display = 'none';
    rtspCameraSetup.style.display = 'none';
    serialDeviceSelect.required = false;
    rtspUrlInput.required = false;
    serialDeviceSelect.innerHTML = '';
    serialDeviceSelect.style.display = 'none';
    noSerialDeviceMessage.style.display = 'none';
    serialLoading.style.display = 'none';
    enablePreview.checked = false;
    hidePreview();
    if (previewUpdateTimeout) {
        clearTimeout(previewUpdateTimeout);
    }
});

