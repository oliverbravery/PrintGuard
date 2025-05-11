// filepath: sw.js
self.addEventListener('push', function(event) {
  let data = {};
  if (event.data) {
    data = event.data.json();
  }
  const title = data.title || 'Notification';
  const options = {
    body: data.body || '',
    data: data,
    icon: data.icon || '',
    image: data.image || ''
  };
  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const url = event.notification.data?.url || event.notification.body;
  if (url) {
    const fullUrl = new URL(url, self.location.origin).href;
    event.waitUntil(
      clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
        for (const client of windowClients) {
          if (client.url === fullUrl && 'focus' in client) {
            return client.focus();
          }
        }
        return clients.openWindow(fullUrl);
      })
    );
  }
});
