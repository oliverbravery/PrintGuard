// Service worker for PrintGuard Push Notifications
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', event => {
  let notificationTitle = 'PrintGuard Alert';
  let notificationBody = 'Print detection alert!';
  if (event.data) {
    try {
      const jsonData = event.data.json();
      if (typeof jsonData === 'object' && jsonData !== null) {
        notificationBody = jsonData.body || jsonData.message || JSON.stringify(jsonData);
        if(jsonData.title) notificationTitle = jsonData.title;
      } else {
        notificationBody = jsonData;
      }
    } catch (e) {
      console.warn('Failed to parse payload directly as JSON, trying as text:', e);
      const textData = event.data.text();
      try {
        const parsedTextData = JSON.parse(textData);
        if (typeof parsedTextData === 'object' && parsedTextData !== null) {
          notificationBody = parsedTextData.body || parsedTextData.message || JSON.stringify(parsedTextData);
          if(parsedTextData.title) notificationTitle = parsedTextData.title;
        } else {
          notificationBody = parsedTextData;
        }
      } catch (e2) {
        console.warn('Failed to parse text data as JSON, using text data as body:', e2);
        notificationBody = textData;
      }
    }
  }
  
  event.waitUntil(
    self.registration.showNotification(notificationTitle, {
      body: notificationBody,
      vibrate: [100, 50, 100],
      timestamp: Date.now(),
      requireInteraction: true
    }).catch(err => {
      console.error('Error showing notification:', err);
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow('/')
  );
});

