import assert from "node:assert/strict";
import test from "node:test";
import {
  FACTS,
  PRODUCT_SCREENS,
  WORKFLOW_STEPS,
  buildServiceUrl,
  getAdjacentProductScreenIndex,
  getProductGalleryIds,
  getProductTabKeyAction,
} from "./landing-content";

test("제품 증거는 실제 화면 5개를 정해진 순서로 제공한다", () => {
  assert.deepEqual(
    PRODUCT_SCREENS.map(({ id }) => id),
    ["dashboard", "customers", "coverage", "compare", "schedule"],
  );
});

test("각 제품 화면은 실제 이미지와 핵심 설명을 제공한다", () => {
  for (const screen of PRODUCT_SCREENS) {
    assert.match(screen.image, /^\/landing-test\/.+\.webp$/);
    assert.ok(screen.imageAlt.length > 0);
    assert.ok(screen.highlights.length >= 2 && screen.highlights.length <= 3);
  }
});

test("증권 비교 화면은 여러 증권의 중립 시각 비교로 설명한다", () => {
  const compare = PRODUCT_SCREENS.find(({ id }) => id === "compare");

  assert.equal(compare?.label, "증권 비교");
  assert.match(compare?.title ?? "", /여러 증권/);
  assert.doesNotMatch(
    JSON.stringify({ compare, WORKFLOW_STEPS }),
    /현재와 제안|갈아타기|승환|비교안내서/,
  );
});

test("각 제품 화면은 원본 이미지 비율을 제공한다", () => {
  const expectedDimensions = [
    [1200, 570],
    [1200, 525],
    [1440, 1089],
    [1440, 442],
    [1440, 590],
  ];

  assert.deepEqual(
    PRODUCT_SCREENS.map((screen) => [screen.width, screen.height]),
    expectedDimensions,
  );
});

test("제품 탭 화살표 이동은 양 끝에서 순환한다", () => {
  assert.equal(
    getAdjacentProductScreenIndex(0, "ArrowLeft"),
    PRODUCT_SCREENS.length - 1,
  );
  assert.equal(
    getAdjacentProductScreenIndex(
      PRODUCT_SCREENS.length - 1,
      "ArrowRight",
    ),
    0,
  );
  assert.equal(getAdjacentProductScreenIndex(2, "ArrowLeft"), 1);
  assert.equal(getAdjacentProductScreenIndex(2, "ArrowRight"), 3);
});

test("제품 탭 키는 이동과 선택 동작을 명확히 구분한다", () => {
  assert.deepEqual(
    ["Enter", " ", "ArrowLeft", "ArrowRight", "Escape"].map((key) =>
      getProductTabKeyAction(key),
    ),
    ["select", "select", "move-left", "move-right", "none"],
  );
});

test("제품 탭과 확대 제목은 화면별 고유 ID를 가진다", () => {
  assert.deepEqual(getProductGalleryIds("customers"), {
    tabId: "landing-test-product-tab-customers",
    panelId: "landing-test-product-panel-customers",
    dialogTitleId: "landing-test-product-dialog-title-customers",
  });
});

test("고객관리 화면은 개인정보 보호 처리 안내를 포함한다", () => {
  const customers = PRODUCT_SCREENS.find(({ id }) => id === "customers");

  assert.equal(customers?.privacyNote, "일부 개인정보 보호 처리");
});

test("핵심 사실과 사용 흐름 수를 고정한다", () => {
  assert.equal(FACTS.length, 3);
  assert.equal(WORKFLOW_STEPS.length, 4);
});

test("서비스 링크에 원래 UTM을 보존한다", () => {
  assert.equal(
    buildServiceUrl("/register", "?utm_source=nav&utm_campaign=test"),
    "https://www.inpa.kr/register?utm_source=nav&utm_campaign=test",
  );
});

test("서비스 링크는 UTM 이외 검색값을 옮기지 않는다", () => {
  assert.equal(
    buildServiceUrl("/login", "?utm_medium=cpc&next=/admin&ref=partner"),
    "https://www.inpa.kr/login?utm_medium=cpc",
  );
});

test("서비스 링크는 경로에 있던 UTM을 새 값으로 덮어쓰지 않는다", () => {
  assert.equal(
    buildServiceUrl(
      "/register?utm_source=hero",
      "?utm_source=nav&utm_campaign=launch",
    ),
    "https://www.inpa.kr/register?utm_source=hero&utm_campaign=launch",
  );
});

test("서비스 링크는 중복된 UTM 키의 첫 값을 유지한다", () => {
  assert.equal(
    buildServiceUrl(
      "/register",
      "?utm_source=first&utm_source=second&utm_campaign=launch",
    ),
    "https://www.inpa.kr/register?utm_source=first&utm_campaign=launch",
  );
});

test("브라우저 검색값이 없어도 서비스 링크를 만든다", () => {
  assert.equal(buildServiceUrl("/register"), "https://www.inpa.kr/register");
});
