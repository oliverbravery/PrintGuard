export { registerPush, unsubscribeFromPush };

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
        if ('Notification' in window && Notification.permission !== 'granted') {
            const permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                throw new Error('Notification permission denied');
            }
            console.debug('Notification permission newly granted');
        }
        
        if ('serviceWorker' in navigator) {
            const registrations = await navigator.serviceWorker.getRegistrations();
            for (let registration of registrations) {
                await registration.unregister();
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
                } else {
                    resolve();
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
        if (Notification.permission === 'granted') {
            return true;
        } else {
            throw new Error('Permission appears granted but notification state is inconsistent');
        }
    } catch (error) {
        console.error('Failed to register for push notifications:', error);
        alert('Failed to enable notifications: ' + error.message);
        return false;
    }
}

async function unsubscribeFromPush() {
    try {
        if (!('serviceWorker' in navigator)) {
            throw new Error('Service workers are not supported in this browser');
        }
        const registrations = await navigator.serviceWorker.getRegistrations();
        let hadSubscription = false;
        for (let registration of registrations) {
            const subscription = await registration.pushManager.getSubscription();
            if (subscription) {
                await subscription.unsubscribe();
                hadSubscription = true;
            }
            await registration.unregister();
        }
        return true;
    } catch (error) {
        console.error('Failed to unsubscribe from push notifications:', error);
        alert('Failed to disable notifications: ' + error.message);
        return false;
    }
}

if ('serviceWorker' in navigator) {
    window.addEventListener('load', async () => {
        try {
            console.debug('Page loaded, service workers will be managed by notification functions');
        } catch (error) {
            console.error('Error managing service workers on page load:', error);
        }
    });
}