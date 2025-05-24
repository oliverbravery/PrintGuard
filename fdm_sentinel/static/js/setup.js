import { render_ascii_title } from './utils.js';

document.addEventListener('DOMContentLoaded', () => {
    const asciiTitle = document.getElementById('ascii-title');
    render_ascii_title(asciiTitle, 'FDM\nSetup');

    const setupState = {
        vapidConfigured: false,
        sslConfigured: false,
        vapidData: {},
        sslData: {}
    };

    function showSection(sectionId) {
        document.querySelectorAll('.setup-section').forEach(section => {
            section.classList.remove('active');
        });
        document.getElementById(`${sectionId}-section`).classList.add('active');
        document.querySelectorAll('.progress-step').forEach(step => {
            step.classList.remove('active');
            const stepId = step.dataset.step;
            if (stepId === sectionId) {
                step.classList.add('active');
            } else if (
                (stepId === 'vapid' && setupState.vapidConfigured) ||
                (stepId === 'ssl' && setupState.sslConfigured)
            ) {
                step.classList.add('completed');
            }
        });

        if (sectionId === 'finish') {
            document.getElementById('summary-vapid-status').textContent = 
                setupState.vapidConfigured ? 'Configured ✓' : 'Not Configured';
            document.getElementById('summary-vapid-status').className = 
                setupState.vapidConfigured ? 'status-configured' : '';
            
            document.getElementById('summary-ssl-status').textContent = 
                setupState.sslConfigured ? 'Configured ✓' : 'Not Configured';
            document.getElementById('summary-ssl-status').className = 
                setupState.sslConfigured ? 'status-configured' : '';
        }
    }

    document.getElementById('generate-vapid-keys-btn').addEventListener('click', async () => {
        try {
            const response = await fetch('/setup/generate-vapid-keys', { method: 'POST' });
            if (response.ok) {
                const data = await response.json();
                document.getElementById('vapid-public-key').value = data.public_key;
                document.getElementById('vapid-private-key').value = data.private_key;
                document.getElementById('vapid-subject').value = data.subject ? data.subject.replace('mailto:', '') : '';
                document.getElementById('vapid-form').style.display = 'block';
            } else {
                alert('Failed to generate VAPID keys');
            }
        } catch (error) {
            console.error('Error generating VAPID keys:', error);
            alert('Error generating VAPID keys');
        }
    });

    document.getElementById('import-vapid-keys-btn').addEventListener('click', () => {
        document.getElementById('vapid-form').style.display = 'block';
    });

    document.getElementById('save-vapid-settings').addEventListener('click', async () => {
        const publicKey = document.getElementById('vapid-public-key').value.trim();
        const privateKey = document.getElementById('vapid-private-key').value.trim();
        const subjectInput = document.getElementById('vapid-subject').value.trim();
        const subject = 'mailto:' + subjectInput;
        const baseUrlInput = document.getElementById('base-url').value.trim();
        const baseUrl = 'https://' + baseUrlInput;
        
        if (!publicKey || !privateKey || !subjectInput || !baseUrlInput) {
            alert('All fields are required');
            return;
        }
        
        try {
            const response = await fetch('/setup/save-vapid-settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ public_key: publicKey, private_key: privateKey, subject, base_url: baseUrl })
            });
            
            if (response.ok) {
                setupState.vapidConfigured = true;
                setupState.vapidData = { publicKey, privateKey, subject, baseUrl };
                showSection('ssl');
            } else {
                const error = await response.json();
                alert(`Failed to save VAPID settings: ${error.detail}`);
            }
        } catch (error) {
            console.error('Error saving VAPID settings:', error);
            alert('Error saving VAPID settings');
        }
    });

    document.getElementById('generate-ssl-cert-btn').addEventListener('click', async () => {
        try {
            const response = await fetch('/setup/generate-ssl-cert', { method: 'POST' });
            if (response.ok) {
                setupState.sslConfigured = true;
                setupState.sslData = { generated: true };
                alert('SSL certificate generated successfully');
                showSection('finish');
            } else {
                alert('Failed to generate SSL certificate');
            }
        } catch (error) {
            console.error('Error generating SSL certificate:', error);
            alert('Error generating SSL certificate');
        }
    });

    document.getElementById('import-ssl-cert-btn').addEventListener('click', () => {
        document.getElementById('ssl-import-form').style.display = 'block';
    });

    document.getElementById('save-ssl-settings').addEventListener('click', async () => {
        const certFile = document.getElementById('ssl-cert-file').files[0];
        const keyFile = document.getElementById('ssl-key-file').files[0];
        
        if (!certFile || !keyFile) {
            alert('Both certificate and key files are required');
            return;
        }
        
        const formData = new FormData();
        formData.append('cert_file', certFile);
        formData.append('key_file', keyFile);
        
        try {
            const response = await fetch('/setup/upload-ssl-cert', {
                method: 'POST',
                body: formData
            });
            
            if (response.ok) {
                setupState.sslConfigured = true;
                setupState.sslData = { imported: true };
                showSection('finish');
            } else {
                const error = await response.json();
                alert(`Failed to upload SSL certificate: ${error.detail}`);
            }
        } catch (error) {
            console.error('Error uploading SSL certificate:', error);
            alert('Error uploading SSL certificate');
        }
    });

    document.getElementById('finish-setup-btn').addEventListener('click', async () => {
        alert('Setup complete! To finalize, please restart the server. Redirecting to the home page...');
        window.location.href = '/';
    });
});