document.addEventListener('DOMContentLoaded', async function() {
    const enrollmentUrl = `${window.location.protocol}//${window.location.hostname}:${window.location.port || (window.location.protocol === 'https:' ? '443' : '8000')}/setup/warp/add-device`;
    document.getElementById('enrollment-url').textContent = enrollmentUrl;
    await fetchWarpConfig();
    const qr = new QRious({
        element: document.getElementById('qr-code'),
        value: enrollmentUrl,
        size: 200,
        level: 'M',
        background: 'white',
        foreground: 'black',
        padding: 2
    });
    try {
        qr.value = enrollmentUrl;
    } catch (err) {
        console.error('QR Code generation failed:', err);
        document.getElementById('qr-code').style.display = 'none';
    }
    document.getElementById('copy-url-btn').addEventListener('click', function() {
        const button = this;
        navigator.clipboard.writeText(enrollmentUrl).then(() => {
            const originalText = button.textContent;
            button.textContent = '✓ Copied!';
            setTimeout(() => {
                button.textContent = originalText;
            }, 2000);
        }).catch((error) => {
            console.error('Clipboard API failed, using fallback:', error);
            const textArea = document.createElement('textarea');
            textArea.value = enrollmentUrl;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            const originalText = button.textContent;
            button.textContent = '✓ Copied!';
            setTimeout(() => {
                button.textContent = originalText;
            }, 2000);
        });
    });
    document.getElementById('device-info').textContent = 
        `${navigator.platform} - ${navigator.userAgent.split(' ')[0]}`;

    async function fetchWarpConfig() {
        try {
            const response = await fetch('/setup/warp/team-name');
            if (response.ok) {
                const data = await response.json();
                document.getElementById('team-name').textContent = data.team_name || 'your-organization';
                const siteDomain = data.site_domain || 'your-cloudflare-domain.com';
                const domainElement = document.getElementById('site-domain');
                if (domainElement) {
                    domainElement.textContent = `https://${siteDomain}`;
                }
            } else {
                console.warn('Could not fetch WARP config, using defaults');
                document.getElementById('team-name').textContent = 'your-organization';
                const domainElement = document.getElementById('site-domain');
                if (domainElement) {
                    domainElement.textContent = 'your-cloudflare-domain.com';
                }
            }
        } catch (error) {
            console.error('Error fetching WARP config:', error);
            document.getElementById('team-name').textContent = 'your-organization';
            const domainElement = document.getElementById('site-domain');
            if (domainElement) {
                domainElement.textContent = 'your-cloudflare-domain.com';
            }
        }
    }
});
