const CACHE_NAME = 'box-inventory-v1';

const ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './config.json',
  './src/icons/icon.svg',
  './src/js/app.js',
  './src/js/config.js',
  './src/js/resolve.js',
  './data/snapshot.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  
  // Do not cache the Google Sheets API responses or Cloud Run calls
  if (url.hostname.includes('docs.google.com') || url.hostname.includes('run.app')) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cachedResponse => {
      const fetchPromise = fetch(event.request).then(networkResponse => {
        if (networkResponse && networkResponse.ok && event.request.method === 'GET') {
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, networkResponse.clone());
          });
        }
        return networkResponse;
      }).catch(err => {
        console.warn('Network fetch failed, using cache:', err);
      });
      return cachedResponse || fetchPromise;
    })
  );
});
