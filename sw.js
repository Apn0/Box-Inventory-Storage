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
  if (event.request.method !== 'GET') {
    return;
  }

  const url = new URL(event.request.url);
  
  // Do not cache Google Sheets API, Cloud Run, or server API / proxy calls
  if (
    url.hostname.includes('docs.google.com') ||
    url.hostname.includes('run.app') ||
    url.pathname.startsWith('/proxy') ||
    url.pathname.startsWith('/confirm') ||
    url.pathname.startsWith('/dismiss') ||
    url.pathname.startsWith('/quickadd') ||
    url.pathname.startsWith('/undo')
  ) {
    return;
  }

  // Network-first for dynamic data
  if (url.pathname.endsWith('/data/inventory.json') || url.pathname.endsWith('/config.json')) {
    event.respondWith(
      fetch(event.request).then(networkResponse => {
        if (networkResponse && networkResponse.ok) {
          const clone = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return networkResponse;
      }).catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cachedResponse => {
      const fetchPromise = fetch(event.request).then(networkResponse => {
        if (networkResponse && networkResponse.ok) {
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, networkResponse.clone());
          });
        }
        return networkResponse;
      }).catch(err => {
        console.warn('Network fetch failed, using cache:', err);
        if (event.request.mode === 'navigate') {
          return caches.match('./index.html') || caches.match('./');
        }
        return null;
      });
      return cachedResponse || fetchPromise;
    })
  );
});
