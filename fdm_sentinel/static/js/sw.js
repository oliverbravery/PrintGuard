self.addEventListener('push', function(event) {
  console.log('Service Worker: Push event received', event);
  let data = {};
  if (event.data) {
    data = event.data.json();
  }
  const title = data.title || 'Notification';
  const options = {
    body: data.body || '',
    data: data,
    icon: data.icon || '', // You might want to add a default icon
    image: data.image || ''
  };
  event.waitUntil(
    (async () => {
      await self.registration.showNotification(title, options);
      console.log('Service Worker: Notification displayed', title, options);
    })()
  );
});

self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});

self.addEventListener('notificationclick', function(event) {
  console.log('Service Worker: Notification click event', event);
  event.notification.close();
  const url = event.notification.data?.url || event.notification.body; // Use data.url if present, otherwise body as fallback
  if (url) {
    // Ensure the URL is absolute
    const fullUrl = new URL(url, self.location.origin).href;
    event.waitUntil(
      clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
        // Check if a window with this URL already exists.
        for (const client of windowClients) {
          if (client.url === fullUrl && 'focus' in client) {
            return client.focus();
          }
        }
        // If not, open a new window.
        return clients.openWindow(fullUrl);
      })
    );
  }
});
