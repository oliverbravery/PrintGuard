import { render_ascii_title } from './utils.js';

document.addEventListener('DOMContentLoaded', () => {
    const asciiTitle = document.getElementById('ascii-title');
    render_ascii_title(asciiTitle, 'PrintGuard');

    const setupState = {
        networkConfigured: false,
        vapidConfigured: false,
        sslConfigured: false,
        tunnelConfigured: false,
        tunnelInitialized: false,
        cloudflareDownloadConfigured: false,
        networkData: {},
        vapidData: {},
        sslData: {},
        tunnelData: {},
        tunnelToken: null
    };

    function showSection(sectionId) {
        document.querySelectorAll('.setup-section').forEach(section => {
            section.classList.remove('active');
        });
        document.getElementById(`${sectionId}-section`).classList.add('active');
        if (sectionId === 'vapid' && selectedNetworkOption === 'external' && setupState.tunnelInitialized) {
            const tunnelUrl = setupState.tunnelData.url;
            if (tunnelUrl) {
                const domain = tunnelUrl.replace(/^https?:\/\//, '');
                document.getElementById('base-url').value = domain;
            }
        }
        let progressContainer;
        if (selectedNetworkOption === 'external') {
            if (selectedTunnelProvider === 'ngrok') {
                progressContainer = document.getElementById('setup-progress-ngrok');
            } else if (selectedTunnelProvider === 'cloudflare') {
                progressContainer = document.getElementById('setup-progress-cloudflare');
            } else {
                progressContainer = document.getElementById('setup-progress-external');
            }
        } else {
            progressContainer = document.getElementById('setup-progress');
        }
            
        progressContainer.querySelectorAll('.progress-step').forEach(step => {
            step.classList.remove('active');
            const stepId = step.dataset.step;
            if (stepId === sectionId) {
                step.classList.add('active');
            } else            if (
                (stepId === 'vapid' && setupState.vapidConfigured) ||
                (stepId === 'ssl' && setupState.sslConfigured) ||
                (stepId === 'tunnel' && setupState.tunnelConfigured) ||
                (stepId === 'tunnel-config' && setupState.tunnelConfigured) ||
                (stepId === 'initialize' && setupState.tunnelInitialized) ||
                (stepId === 'cloudflare-download' && setupState.cloudflareDownloadConfigured)
            ) {
                step.classList.add('completed');
            }
        });

        if (sectionId === 'finish') {
            document.getElementById('summary-network-status').textContent = 
                setupState.networkConfigured ? 'Configured ✓' : 'Not Configured';
            document.getElementById('summary-network-status').className = 
                setupState.networkConfigured ? 'status-configured' : '';
            
            if (selectedNetworkOption === 'external') {
                document.getElementById('tunnel-summary-item').style.display = 'block';
                const tunnelStatus = setupState.tunnelInitialized ? 'Initialized ✓' : 
                                   setupState.tunnelConfigured ? 'Configured (Not Initialized)' : 'Not Configured';
                document.getElementById('summary-tunnel-status').textContent = tunnelStatus;
                document.getElementById('summary-tunnel-status').className = 
                    setupState.tunnelInitialized ? 'status-configured' : '';
                document.getElementById('vapid-summary-item').style.display = 'block';
                document.getElementById('summary-vapid-status').textContent = 
                    setupState.vapidConfigured ? 'Configured ✓' : 'Not Configured';
                document.getElementById('summary-vapid-status').className = 
                    setupState.vapidConfigured ? 'status-configured' : '';
                document.getElementById('ssl-summary-item').style.display = 'none';
            } else {
                document.getElementById('tunnel-summary-item').style.display = 'none';
                document.getElementById('vapid-summary-item').style.display = 'block';
                document.getElementById('ssl-summary-item').style.display = 'block';
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
    }

    let selectedNetworkOption = null;

    document.getElementById('local-network-btn').addEventListener('click', () => {
        selectedNetworkOption = 'local';
        document.querySelectorAll('.network-option').forEach(btn => btn.classList.remove('selected'));
        document.getElementById('local-network-btn').classList.add('selected');
        document.getElementById('setup-progress').style.display = 'flex';
        document.getElementById('network-section').style.display = 'none';
        setupState.networkConfigured = true;
        setupState.networkData = { type: selectedNetworkOption };
        showSection('vapid');
    });

    document.getElementById('external-network-btn').addEventListener('click', () => {
        selectedNetworkOption = 'external';
        document.querySelectorAll('.network-option').forEach(btn => btn.classList.remove('selected'));
        document.getElementById('external-network-btn').classList.add('selected');
        document.getElementById('setup-progress-external').style.display = 'flex';
        document.getElementById('network-section').style.display = 'none';
        setupState.networkConfigured = true;
        setupState.networkData = { type: selectedNetworkOption };
        showSection('tunnel');
    });

    let selectedTunnelProvider = null;

    document.getElementById('ngrok-btn').addEventListener('click', () => {
        selectedTunnelProvider = 'ngrok';
        document.querySelectorAll('.tunnel-option').forEach(btn => btn.classList.remove('selected'));
        document.getElementById('ngrok-btn').classList.add('selected');
        document.getElementById('tunnel-form').style.display = 'block';
        document.getElementById('ngrok-config').style.display = 'block';
        document.getElementById('cloudflare-config').style.display = 'none';
        document.getElementById('setup-progress-external').style.display = 'none';
        document.getElementById('setup-progress-cloudflare').style.display = 'none';
        document.getElementById('setup-progress-ngrok').style.display = 'flex';
    });

    document.getElementById('cloudflare-btn').addEventListener('click', () => {
        selectedTunnelProvider = 'cloudflare';
        document.querySelectorAll('.tunnel-option').forEach(btn => btn.classList.remove('selected'));
        document.getElementById('cloudflare-btn').classList.add('selected');
        document.getElementById('tunnel-form').style.display = 'block';
        document.getElementById('cloudflare-config').style.display = 'block';
        document.getElementById('ngrok-config').style.display = 'none';
        document.getElementById('setup-progress-external').style.display = 'none';
        document.getElementById('setup-progress-ngrok').style.display = 'none';
        document.getElementById('setup-progress-cloudflare').style.display = 'flex';
    });

    document.getElementById('cloudflare-global-key').addEventListener('change', (e) => {
        const emailGroup = document.getElementById('cloudflare-email-group');
        if (e.target.checked) {
            emailGroup.style.display = 'block';
        } else {
            emailGroup.style.display = 'none';
            document.getElementById('cloudflare-email').value = '';
        }
    });

    document.getElementById('save-tunnel-settings').addEventListener('click', async () => {
        if (!selectedTunnelProvider) {
            alert('Please select a tunnel provider');
            return;
        }
        let token = '';
        let domain = '';
        let email = '';
        if (selectedTunnelProvider === 'ngrok') {
            token = document.getElementById('ngrok-auth-token').value.trim();
            domain = document.getElementById('ngrok-domain').value.trim();
        } else if (selectedTunnelProvider === 'cloudflare') {
            token = document.getElementById('cloudflare-api-key').value.trim();
            const isGlobalKey = document.getElementById('cloudflare-global-key').checked;
            if (isGlobalKey) {
                email = document.getElementById('cloudflare-email').value.trim();
                if (!email) {
                    alert('Please enter your account email for Global API Key');
                    return;
                }
            }
        }
        if (!token) {
            alert('Please enter the required API key');
            return;
        }
        if (selectedTunnelProvider === 'ngrok' && !domain) {
            alert('Please enter the required ngrok static domain');
            return;
        }
        try {
            const response = await fetch('/setup/save-tunnel-settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    provider: selectedTunnelProvider,
                    token: token,
                    domain: domain,
                    email: email
                })
            });
            
            if (response.ok) {
                const result = await response.json();
                setupState.tunnelConfigured = true;
                setupState.tunnelData = { provider: selectedTunnelProvider, token, domain };
                if (selectedTunnelProvider === 'ngrok') {
                    showSection('initialize');
                    initializeNgrokTunnel();
                } else if (selectedTunnelProvider === 'cloudflare') {
                    showSection('tunnel-config');
                    fetchCloudflareAccountsZones();
                }
            } else {
                const error = await response.json();
                alert(`Failed to save tunnel settings: ${error.detail}`);
            }
        } catch (error) {
            console.error('Error saving tunnel settings:', error);
            alert('Error saving tunnel settings');
        }
    });

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
                if (selectedNetworkOption === 'external' && selectedTunnelProvider === 'cloudflare') {
                    showSection('cloudflare-download');
                } else if (selectedNetworkOption === 'external') {
                    showSection('finish');
                } else {
                    showSection('ssl');
                }
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

    document.getElementById('save-ssl-settings').addEventListener('click', () => {
        showSection('finish');
    });

    document.getElementById('finish-setup-btn').addEventListener('click', async () => {
        try {
            const startupMode = selectedNetworkOption === 'external' ? 'tunnel' : 'local';
            const completionData = {
                startup_mode: startupMode
            };
            if (selectedNetworkOption === 'external' && selectedTunnelProvider) {
                completionData.tunnel_provider = selectedTunnelProvider;
            }
            const response = await fetch('/setup/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(completionData)
            });
            if (response.ok) {
                alert('Setup complete! To finalize, please restart the server. Redirecting to setup page...');
                window.location.href = '/setup';
            } else {
                const error = await response.json();
                alert(`Failed to complete setup: ${error.detail}`);
            }
        } catch (error) {
            console.error('Error completing setup:', error);
            alert('Error completing setup');
        }
    });

    document.getElementById('continue-to-finish').addEventListener('click', () => {
        if (selectedNetworkOption === 'external') {
            showSection('vapid');
        } else {
            showSection('finish');
        }
    });

    document.getElementById('retry-initialization').addEventListener('click', () => {
        initializeNgrokTunnel();
    });

    document.getElementById('back-to-tunnel-config').addEventListener('click', () => {
        showSection('tunnel');
    });

    async function initializeNgrokTunnel() {
        document.getElementById('initialization-loading').style.display = 'block';
        document.getElementById('initialization-success').style.display = 'none';
        document.getElementById('initialization-error').style.display = 'none';
        try {
            const response = await fetch('/setup/initialize-ngrok-tunnel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            const result = await response.json();
            if (response.ok && result.success) {
                document.getElementById('initialization-loading').style.display = 'none';
                document.getElementById('initialization-success').style.display = 'block';
                document.getElementById('provider-name').textContent = result.provider || selectedTunnelProvider;
                document.getElementById('provider-url').textContent = result.url || 'N/A';
                setupState.tunnelInitialized = true;
                setupState.tunnelData = { ...setupState.tunnelData, ...result };
            } else {
                document.getElementById('initialization-loading').style.display = 'none';
                document.getElementById('initialization-error').style.display = 'block';
                document.getElementById('error-message').textContent = result.message || 'Unknown error occurred';
            }
        } catch (error) {
            console.error('Error initializing tunnel provider:', error);
            document.getElementById('initialization-loading').style.display = 'none';
            document.getElementById('initialization-error').style.display = 'block';
            document.getElementById('error-message').textContent = 'Network error: Unable to connect to server';
        } finally {
            document.getElementById('initialization-loading').style.display = 'none';
        }
    }

    async function fetchCloudflareAccountsZones() {
        document.getElementById('cloudflare-selection-loading').style.display = 'block';
        document.getElementById('cloudflare-selection-content').style.display = 'none';
        document.getElementById('cloudflare-selection-error').style.display = 'none';
        
        try {
            const response = await fetch('/setup/cloudflare/accounts-zones');
            const result = await response.json();
            
            if (response.ok && result.success) {
                populateAccountsAndZones(result.accounts, result.zones);
                document.getElementById('cloudflare-selection-loading').style.display = 'none';
                document.getElementById('cloudflare-selection-content').style.display = 'block';
            } else {
                document.getElementById('cloudflare-selection-loading').style.display = 'none';
                document.getElementById('cloudflare-selection-error').style.display = 'block';
                document.getElementById('cloudflare-error-message').textContent = result.detail || 'Unknown error occurred';
            }
        } catch (error) {
            console.error('Error fetching Cloudflare accounts and zones:', error);
            document.getElementById('cloudflare-selection-loading').style.display = 'none';
            document.getElementById('cloudflare-selection-error').style.display = 'block';
            document.getElementById('cloudflare-error-message').textContent = 'Network error: Unable to connect to server';
        }
    }

    function populateAccountsAndZones(accounts, zones) {
        const accountSelect = document.getElementById('cloudflare-account-select');
        const zoneSelect = document.getElementById('cloudflare-zone-select');
        accountSelect.innerHTML = '<option value="">Choose an account...</option>';
        zoneSelect.innerHTML = '<option value="">Choose a domain...</option>';
        accounts.forEach(account => {
            const option = document.createElement('option');
            option.value = account.id;
            option.textContent = account.name;
            accountSelect.appendChild(option);
        });
        zones.forEach(zone => {
            const option = document.createElement('option');
            option.value = zone.id;
            option.textContent = zone.name;
            option.setAttribute('data-name', zone.name);
            zoneSelect.appendChild(option);
        });
    }

    document.getElementById('cloudflare-zone-select').addEventListener('change', (e) => {
        const selectedOption = e.target.selectedOptions[0];
        const domainSuffix = document.getElementById('domain-suffix');
        if (selectedOption && selectedOption.value) {
            const domainName = selectedOption.getAttribute('data-name');
            domainSuffix.textContent = '.' + domainName;
        } else {
            domainSuffix.textContent = '.example.com';
        }
    });

    document.getElementById('configure-cloudflare-tunnel').addEventListener('click', async () => {
        const accountId = document.getElementById('cloudflare-account-select').value;
        const zoneId = document.getElementById('cloudflare-zone-select').value;
        const subdomain = document.getElementById('cloudflare-subdomain').value.trim();
        if (!accountId) {
            alert('Please select a Cloudflare account');
            return;
        }
        if (!zoneId) {
            alert('Please select a domain');
            return;
        }
        if (!subdomain) {
            alert('Please enter a subdomain');
            return;
        }
        document.getElementById('cloudflare-selection-content').style.display = 'none';
        document.getElementById('cloudflare-tunnel-loading').style.display = 'block';
        try {
            const response = await fetch('/setup/cloudflare/create-tunnel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_id: accountId,
                    zone_id: zoneId,
                    subdomain: subdomain
                })
            });
            if (response.ok) {
                const result = await response.json();
                setupState.tunnelInitialized = true;
                setupState.tunnelData = { ...setupState.tunnelData, ...result };
                showSection('vapid');
                if (result.url) {
                    document.getElementById('base-url').value = result.url;
                }
            }
            else {
                document.getElementById('cloudflare-tunnel-loading').style.display = 'none';
                document.getElementById('cloudflare-selection-content').style.display = 'block';
                const error = await response.json();
                alert(`Failed to create Cloudflare tunnel: ${error.detail}`);
            }
        } catch (error) {
            document.getElementById('cloudflare-tunnel-loading').style.display = 'none';
            document.getElementById('cloudflare-selection-content').style.display = 'block';
            console.error('Error creating Cloudflare tunnel:', error);
            alert('Error creating Cloudflare tunnel');
        }
    });

    document.getElementById('retry-cloudflare-fetch').addEventListener('click', () => {
        fetchCloudflareAccountsZones();
    });

    document.getElementById('back-to-tunnel-settings').addEventListener('click', () => {
        showSection('tunnel');
    });

    let selectedOperatingSystem = null;

    document.getElementById('macos-btn').addEventListener('click', () => {
        selectedOperatingSystem = 'macos';
        document.querySelectorAll('.os-option').forEach(btn => btn.classList.remove('selected'));
        document.getElementById('macos-btn').classList.add('selected');
        saveOperatingSystemSelection();
    });

    document.getElementById('windows-btn').addEventListener('click', () => {
        selectedOperatingSystem = 'windows';
        document.querySelectorAll('.os-option').forEach(btn => btn.classList.remove('selected'));
        document.getElementById('windows-btn').classList.add('selected');
        saveOperatingSystemSelection();
    });

    document.getElementById('linux-btn').addEventListener('click', () => {
        selectedOperatingSystem = 'linux';
        document.querySelectorAll('.os-option').forEach(btn => btn.classList.remove('selected'));
        document.getElementById('linux-btn').classList.add('selected');
        saveOperatingSystemSelection();
    });

    async function saveOperatingSystemSelection() {
        try {
            const response = await fetch('/setup/cloudflare/save-os', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ operating_system: selectedOperatingSystem })
            });
            
            if (response.ok) {
                const result = await response.json();
                document.getElementById('tunnel-token-section').style.display = 'block';
                const commandsContainer = document.getElementById('setup-commands-container');
                commandsContainer.innerHTML = '';
                
                if (result.setup_commands && result.setup_commands.length > 0) {
                    result.setup_commands.forEach((command, index) => {
                        const commandDiv = document.createElement('div');
                        commandDiv.className = 'command-display';
                        commandDiv.innerHTML = `
                            <label>Step ${index + 1}:</label>
                            <div class="command-value">${command}</div>
                            <button class="copy-btn" title="Copy to clipboard" onclick="copyToClipboard('${command.replace(/'/g, "\\'")}', this)">📋</button>
                        `;
                        commandsContainer.appendChild(commandDiv);
                    });
                }
                setupState.cloudflareDownloadConfigured = true;
                setupState.tunnelToken = result.tunnel_token;
            } else {
                const error = await response.json();
                console.error('Failed to save OS selection:', error);
                alert(`Failed to save operating system selection: ${error.detail}`);
            }
        } catch (error) {
            console.error('Error saving operating system selection:', error);
            alert('Error saving operating system selection');
        }
    }
    document.getElementById('continue-to-finish_from_cloudflare').addEventListener('click', () => {
        showSection('finish');
    });

    window.copyToClipboard = function(text, button) {
        navigator.clipboard.writeText(text).then(() => {
            const originalText = button.textContent;
            button.textContent = '✓';
            setTimeout(() => {
                button.textContent = originalText;
            }, 2000);
        }).catch((error) => {
            console.error('Clipboard API failed, using fallback:', error);
            const textArea = document.createElement('textarea');
            textArea.value = text;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            
            const originalText = button.textContent;
            button.textContent = '✓';
            setTimeout(() => {
                button.textContent = originalText;
            }, 2000);
        });
    };
});