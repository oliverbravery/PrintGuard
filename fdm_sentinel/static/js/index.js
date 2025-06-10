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
const cameraItems = document.querySelectorAll('.camera-item');
const settingsButton = document.getElementById('settingsButton');
const cameraDisplaySection = document.querySelector('.camera-display-section');
const settingsSection = document.querySelector('.settings-section');
const notificationsBtn = document.getElementById('notificationBtn');

const settingsCameraIndex = document.getElementById('camera_index');
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

const stopDetectionBtnLabel = 'Stop Detection';
const startDetectionBtnLabel = 'Start Detection';

let cameraIndex = 0;

function changeLiveCameraFeed(cameraIndex) {
    camVideoPreview.src = `/camera_feed/${cameraIndex}`;
}

function updateCameraTitle(cameraIndex) {
    const cameraIdText = cameraIndex ? `Camera ${cameraIndex}` : 'No camera selected';
    cameraTitle.textContent = cameraIdText;
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
    settingsCameraIndex.value = d.camera_index;
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
}

function updateSelectedCameraData(d) {
    updateRecentDetectionResult(d.last_result, camPredictionDisplay);
    updateRecentDetectionTime(d.last_time, camPredictionTimeDisplay);
    updateTotalDetectionsCount(d.total_detections, camTotalDetectionsDisplay);
    updateFrameRate(d.frame_rate, camFrameRateDisplay);
    toggleIsDetectingStatus(d.live_detection_running);
    updateDetectionButton(d.live_detection_running);
}

function updateCameraSelectionListData(d) {
    cameraItems.forEach(item => {
        const cameraTextElement = item.querySelector('.camera-text-content span:first-child');
        if (!cameraTextElement) return;

        const cameraIdText = cameraTextElement.textContent;
        const cameraId = cameraIdText.split(': ')[1];

        if (cameraId == d.camera_index) {
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
            item.querySelector('#cameraPreview').src = `/camera_feed/${d.camera_index}`;
        }
    });
}

function updatePolledDetectionData(d) {
    if ('camera_index' in d && d.camera_index == cameraIndex) {
        updateSelectedCameraData(d);
    }
    updateCameraSelectionListData(d);
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
            camera_index: cameraIdx,
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
            majority_vote_window: data.majority_vote_window
        };
        updatePolledDetectionData(metricsData);
        updateSelectedCameraSettings(metricsData);
    })
    .catch(error => {
        console.error(`Error fetching metrics for camera ${cameraIdx}:`, error.message);
        const emptyMetrics = {
            camera_index: cameraIdx,
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
    fetch(`/live/${isStart ? 'start' : 'stop'}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ camera_index: cameraIndex })
    })
    .then(response => {
        if (response.ok) {
            fetchAndUpdateMetricsForCamera(cameraIndex);
        } else {
            response.json().then(errData => {
                console.error(`Failed to ${isStart ? 'start' : 'stop'} live detection for camera ${cameraIndex}. Server: ${errData.detail || response.statusText}`);
            }).catch(() => {
                console.error(`Failed to ${isStart ? 'start' : 'stop'} live detection for camera ${cameraIndex}. Status: ${response.status} ${response.statusText}`);
            });
        }
    })
    .catch(error => {
        console.error(`Network error or exception during ${isStart ? 'start' : 'stop'} request for camera ${cameraIndex}:`, error);
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

render_ascii_title(asciiTitle, 'FDM\nsentinel');

cameraItems.forEach(item => {
    item.addEventListener('click', function() {
        cameraItems.forEach(i => i.classList.remove('selected'));
        this.classList.add('selected');
        const cameraIdText = this.querySelector('.camera-text-content span:first-child').textContent;
        const cameraId = cameraIdText.split(': ')[1];
        if (cameraId && cameraId !== "No cameras available") {
            changeLiveCameraFeed(cameraId); 
        }
        cameraIndex = cameraId;
        updateCameraTitle(cameraId);
        fetchAndUpdateMetricsForCamera(cameraId);
    });
});

document.addEventListener('cameraStateUpdated', evt => {
    if (evt.detail) {
        updatePolledDetectionData(evt.detail);
    }
});

document.addEventListener('DOMContentLoaded', function() {
    cameraItems.forEach(item => {
        item.click();
    });
    const firstCameraItem = cameraItems[0];
    if (firstCameraItem) {
        firstCameraItem.click();
    }
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
    if ('serviceWorker' in navigator) {
        try {
            const registrations = await navigator.serviceWorker.getRegistrations();
            for (const registration of registrations) {
                const subscription = await registration.pushManager.getSubscription();
                if (subscription) {
                    return true;
                }
            }
        } catch (error) {
            console.error('Error checking for active subscriptions:', error);
        }
    }
    
    return false;
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
        const title = isMobileView() ? 'FDM Sentinel' : 'FDM\nsentinel';
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
        detection_interval_ms: parseInt(document.getElementById('detectionInterval').value)
    };
    fetch('/setup/save-feed-settings', {
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
    return fetch('/setup/get-feed-settings', {
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

setupModalOverlay?.addEventListener('click', function(e) {
    if (e.target === setupModalOverlay) {
        setupModalOverlay.style.display = 'none';
        document.body.style.overflow = '';
    }
});

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && setupModalOverlay.style.display === 'flex') {
        setupModalOverlay.style.display = 'none';
        document.body.style.overflow = '';
    }
});
