import assert from "node:assert/strict";
import test from "node:test";
import { resolveNewHostRoute } from "./new-host-routing";

test("new host의 운영 랜딩과 test 후보를 내부 라우트로 보낸다", () => {
  assert.deepEqual(resolveNewHostRoute("/", ""), { kind: "rewrite", target: "/new" });
  assert.deepEqual(resolveNewHostRoute("/test", ""), { kind: "rewrite", target: "/new/test" });
});

test("내부 주소는 공개 주소로 정규화한다", () => {
  assert.deepEqual(resolveNewHostRoute("/new", ""), { kind: "local-redirect", target: "/" });
  assert.deepEqual(resolveNewHostRoute("/new/test", ""), { kind: "local-redirect", target: "/test" });
});

test("그 밖의 서비스 경로와 검색값은 www로 보낸다", () => {
  assert.deepEqual(resolveNewHostRoute("/login", "?utm_source=nav"), {
    kind: "main-redirect",
    target: "https://www.inpa.kr/login?utm_source=nav",
  });
});
