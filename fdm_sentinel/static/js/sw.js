// Service worker for FDM Sentinel Push Notifications
self.addEventListener('install', (event) => {
  console.log('Service Worker installing.');
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  console.log('Service Worker activated.');
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', event => {
  console.log('Push notification received:', event);
  let notificationTitle = 'FDM Sentinel Alert';
  let notificationBody = 'Print detection alert!';
  if (event.data) {
    try {
      const jsonData = event.data.json();
      console.log('Parsed payload directly as JSON:', jsonData);
      if (typeof jsonData === 'object' && jsonData !== null) {
        notificationBody = jsonData.body || jsonData.message || JSON.stringify(jsonData);
        if(jsonData.title) notificationTitle = jsonData.title;
      } else {
        notificationBody = jsonData;
      }
    } catch (e) {
      console.log('Failed to parse payload directly as JSON, trying as text:', e);
      const textData = event.data.text();
      console.log('Parsed payload as text:', textData);
      try {
        const parsedTextData = JSON.parse(textData);
        if (typeof parsedTextData === 'object' && parsedTextData !== null) {
          notificationBody = parsedTextData.body || parsedTextData.message || JSON.stringify(parsedTextData);
          if(parsedTextData.title) notificationTitle = parsedTextData.title;
        } else {
          notificationBody = parsedTextData;
        }
      } catch (e2) {
        console.log('Failed to parse text data as JSON, using text data as body:', e2);
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
    }).then(() => {
      console.log('Notification shown successfully');
    }).catch(err => {
      console.error('Error showing notification:', err);
    })
  );
});

self.addEventListener('notificationclick', event => {
  console.log('Notification clicked:', event);
  event.notification.close();
  event.waitUntil(
    clients.openWindow('/')
  );
});

