const CACHE_NAME = 'jianke-cache-v4';

const STATIC_PRECACHE = [
  '/',
  '/index.html',
  '/manifest.json',
  '/manifest.webmanifest',
  '/pwa-192x192.png',
  '/pwa-512x512.png',
  '/pwa-maskable-192x192.png',
  '/pwa-maskable-512x512.png',
  '/apple-touch-icon.png',
  '/apple-touch-icon-precomposed.png',
  '/favicon.png',
  '/favicon.ico',
  '/wallpaper-fallback.jpg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_PRECACHE).catch((err) => {
        console.warn('Pre-cache warning:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 1. API 接口请求与非 GET 请求：走纯网络
  if (request.method !== 'GET' || url.pathname.startsWith('/api/')) {
    return;
  }

  // 2. 视频文件（mp4 / range 请求）：直接放行
  if (url.pathname.endsWith('.mp4') || request.headers.has('range')) {
    return;
  }

  // 3. 页面导航（HTML）：Network-First，断网时使用缓存
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).then((response) => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      }).catch(() => {
        return caches.match('/index.html') || caches.match('/');
      })
    );
    return;
  }

  // 4. 静态资源（JS, CSS, 字体, 图片）：Stale-While-Revalidate
  event.respondWith(
    caches.match(request).then((cached) => {
      const networkFetch = fetch(request).then((response) => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      }).catch(() => {
        // 网络失败时忽略，已返回 cached
      });
      return cached || networkFetch;
    })
  );
});
