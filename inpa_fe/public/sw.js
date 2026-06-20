// 인파 PWA 서비스워커 — network-first + 오프라인 폴백(최소).
// ★ API(/api)는 절대 캐시하지 않음(인증/개인정보·신선도). GET 자산/문서만 캐시.
const CACHE = "inpa-cache-v1";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  let url;
  try {
    url = new URL(req.url);
  } catch (e) {
    return;
  }
  if (url.origin !== self.location.origin) return; // 외부(CDN/Claude 등) 통과
  if (url.pathname.startsWith("/api")) return;       // API는 항상 네트워크

  event.respondWith(
    fetch(req)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(req))
  );
});
