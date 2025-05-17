const cameraSelect = document.getElementById('cameraSelect');
const videoPreview = document.getElementById('videoPreview');

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
    videoPreview.src = `https://localhost:8000/camera_feed/${cameraSelect.value}`;
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

updateSelectedCamera();