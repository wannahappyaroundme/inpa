// 인파 PWA 서비스워커 — network-first + 오프라인 폴백(최소).
// ★ API(/api)·교차출처는 캐시/가로채기 안 함(인증/개인정보·신선도). 같은 출처 GET 자산/문서만 캐시.
// ★ 네트워크 실패 + 캐시 미스 시 반드시 '유효한 Response'를 반환(undefined 반환 시 SW가 터짐).
const CACHE = "inpa-cache-v2";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
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
  if (url.origin !== self.location.origin) return; // 외부(BE/CDN/Claude 등) 통과 — SW 미개입
  if (url.pathname.startsWith("/api")) return;       // API는 항상 네트워크

  event.respondWith(
    fetch(req)
      .then((res) => {
        // 정상 응답만 캐시(불투명/에러 응답 캐시 금지).
        if (res && res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(async () => {
        const cached = await caches.match(req);
        if (cached) return cached;
        // 캐시도 없으면 — 절대 undefined 반환 금지. 유효한 503 Response 반환.
        return new Response("오프라인이거나 네트워크에 연결할 수 없습니다.", {
          status: 503,
          statusText: "Service Unavailable",
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        });
      })
  );
});
