import assert from "node:assert/strict";
import test from "node:test";
import { resolveLegacyMainRoute, resolveNewHostRoute } from "./new-host-routing";

test("new host의 운영 랜딩은 www 이야기로 영구 이전한다", () => {
  assert.deepEqual(resolveNewHostRoute("/", "?utm_source=old"), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/story?utm_source=old",
  });
});

test("new host의 test 후보는 www 메인으로 영구 이전한다", () => {
  assert.deepEqual(resolveNewHostRoute("/test", "?utm_source=old"), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/?utm_source=old",
  });
});

test("과거 내부 랜딩 주소도 같은 공식 주소로 이전한다", () => {
  assert.deepEqual(resolveNewHostRoute("/new", ""), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/story",
  });
  assert.deepEqual(resolveNewHostRoute("/new/test", ""), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/",
  });
});

test("그 밖의 서비스 경로와 검색값은 www로 보낸다", () => {
  assert.deepEqual(resolveNewHostRoute("/login", "?utm_source=nav"), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/login?utm_source=nav",
  });
});

test("www의 과거 내부 랜딩 주소도 검색값을 보존해 이동한다", () => {
  assert.equal(resolveLegacyMainRoute("/new", "?utm_source=old"), "/story?utm_source=old");
  assert.equal(resolveLegacyMainRoute("/new/test", "?utm_source=old"), "/?utm_source=old");
  assert.equal(resolveLegacyMainRoute("/blog", "?utm_source=old"), null);
});
