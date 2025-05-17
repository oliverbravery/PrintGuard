function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
        .replace(/-/g, '+')
        .replace(/_/g, '/');
    const rawData = atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

async function registerPush() {
    try {
        if ('serviceWorker' in navigator) {
            const registrations = await navigator.serviceWorker.getRegistrations();
            for (let registration of registrations) {
                await registration.unregister();
                console.log('Unregistered old service worker:', registration);
            }
        }
        const {publicKey} = await fetch('/notification/public_key').then(r => r.json());
        const registration = await navigator.serviceWorker.getRegistration('/static/js/sw.js');
        const sw = registration || await navigator.serviceWorker.register('/static/js/sw.js');
        if (sw.active === null) {
            await new Promise(resolve => {
                if (sw.installing) {
                    sw.installing.addEventListener('statechange', e => {
                        if (e.target.state === 'activated') {
                            resolve();
                        }
                    });
                } else if (sw.waiting) {
                    sw.waiting.addEventListener('statechange', e => {
                        if (e.target.state === 'activated') {
                            resolve();
                        }
                    });
                }
            });
        }
        const sub = await sw.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(publicKey)
        });
        await fetch('/notification/subscribe', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(sub)
        });
        console.log('Push notification subscription successful!');
        alert('Notifications enabled successfully!');
    } catch (error) {
        console.error('Failed to register for push notifications:', error);
        alert('Failed to enable notifications: ' + error.message);
    }
}

if ('serviceWorker' in navigator) {
    window.addEventListener('load', async () => {
        try {
            const registrations = await navigator.serviceWorker.getRegistrations();
            for (let registration of registrations) {
                await registration.unregister();
                console.log('Unregistered old service worker on page load:', registration);
            }
        } catch (error) {
            console.error('Error unregistering service workers on page load:', error);
        }
    });
}