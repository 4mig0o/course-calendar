// Keep the shell fresh so an older cached page cannot keep showing a stale
// error. Network-first also lets frontend fixes take effect without asking a
// non-technical user to clear browser storage manually.
const CACHE = "course-calendar-shell-v3";
const SHELL = [
  "/",
  "/static/styles.css?v=20260829-3",
  "/static/app.js?v=20260829-3",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || new URL(event.request.url).origin !== self.location.origin) return;
  if (new URL(event.request.url).pathname === "/static/sw.js") {
    event.respondWith(fetch(event.request));
    return;
  }
  const url = new URL(event.request.url);
  const isShell = url.pathname === "/"
    || url.pathname === "/index.html"
    || url.pathname === "/static/app.js"
    || url.pathname === "/static/styles.css"
    || url.pathname === "/manifest.webmanifest";
  if (!isShell) return;
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy)).catch(() => {});
      }
      return response;
    }).catch(() => caches.match(event.request))
  );
});
