import { registerPush } from './notifications.js';

const cameraSelect = document.getElementById('cameraSelect');
const videoPreview = document.getElementById('videoPreview');
const notificationsBtn = document.getElementById('notificationBtn');

function updateSelectedCameraSettings() {
    fetch(`${document.body.dataset.getSettingsUrl}?`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ camera_index: cameraSelect.value })
    })
        .then(response => response.json())
        .then(settings => {
            document.getElementById('camera_index').value = cameraSelect.value;
            document.getElementById('sensitivity').value = settings.sensitivity;
            document.getElementById('brightness').value = settings.brightness;
            document.getElementById('contrast').value = settings.contrast;
            document.getElementById('focus').value = settings.focus;
            document.getElementById('countdown_time').value = settings.countdown_time;
            document.getElementById('majority_vote_threshold').value = settings.majority_vote_threshold;
            document.getElementById('majority_vote_window').value = settings.majority_vote_window;
            document.querySelectorAll('input[type="range"]').forEach(input => {
                document.getElementById(`${input.id}_val`).textContent = input.value;
            });
        });
}

function updateSelectedCamera() {
    videoPreview.src = `/camera_feed/${cameraSelect.value}`;
    videoPreview.style.display = 'block';
    updateSelectedCameraSettings();
}

cameraSelect.addEventListener('change', function() {
    updateSelectedCamera();
});

document.querySelectorAll('input[type="range"]').forEach(input => {
    input.addEventListener('input', function() {
        document.getElementById(`${input.id}_val`).textContent = input.value;
    });
});

notificationsBtn.addEventListener('click', async () => {
    await registerPush();
});

updateSelectedCamera();