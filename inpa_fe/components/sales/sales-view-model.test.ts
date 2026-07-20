import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  buildRecruitingSalesHref,
  normalizeSalesTab,
  resolveSalesTab,
  type SalesTab,
} from "./sales-view-model";

test("영업 상위 탭은 고객 영업과 설계사 영업만 허용한다", () => {
  const cases: Array<[string | null, SalesTab]> = [
    [null, "customers"],
    ["customers", "customers"],
    ["recruiting", "recruiting"],
    ["unknown", "customers"],
  ];

  cases.forEach(([value, expected]) => {
    assert.equal(normalizeSalesTab(value), expected);
  });
});

test("설계사 영업의 하위 화면은 영업 탭 안의 주소를 유지한다", () => {
  assert.equal(
    buildRecruitingSalesHref("status"),
    "/sales?tab=recruiting&view=status",
  );
  assert.equal(
    buildRecruitingSalesHref("settlement"),
    "/sales?tab=recruiting&view=settlement",
  );
});

test("설계사 영업 공개 스위치를 끄면 고객 영업으로 안전하게 돌아간다", () => {
  assert.equal(resolveSalesTab("recruiting", true), "recruiting");
  assert.equal(resolveSalesTab("recruiting", false), "customers");
  assert.equal(resolveSalesTab("customers", false), "customers");
});

test("대시보드에서는 설계사 영입 바로가기를 빼고 앱 메뉴는 영업으로 묶는다", () => {
  const homeSource = readFileSync("app/home/page.tsx", "utf8");
  const navSource = readFileSync("components/app-nav.tsx", "utf8");

  assert.doesNotMatch(homeSource, /label:\s*["']설계사 영입["']/);
  assert.doesNotMatch(homeSource, /href:\s*["']\/recruiting["']/);
  assert.match(homeSource, /grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5/);
  assert.doesNotMatch(homeSource, /recruiting_enabled \? "lg:grid-cols-6"/);
  assert.match(navSource, /label:\s*["']영업["']/);
  assert.doesNotMatch(navSource, /label:\s*["']설계사 영입["']/);
});

test("영업 탭은 URL 이동을 유지하면서 키보드로 선택할 수 있다", () => {
  const salesShellSource = readFileSync("components/sales/sales-shell.tsx", "utf8");

  assert.match(salesShellSource, /role="tablist"/);
  assert.match(salesShellSource, /role="tab"/);
  assert.match(salesShellSource, /aria-selected=\{active\}/);
  assert.match(salesShellSource, /onKeyDown=\{handleTabKeyDown\}/);

  const handlerStart = salesShellSource.indexOf("const handleTabKeyDown");
  const preventDefault = salesShellSource.indexOf("event.preventDefault()", handlerStart);
  const sameTabReturn = salesShellSource.indexOf(
    "if (nextIndex === currentIndex) return;",
    handlerStart,
  );
  assert.ok(preventDefault > handlerStart);
  assert.ok(preventDefault < sameTabReturn);
});

test("영업 화면은 인증 확인 중에도 빈 화면 대신 로딩 상태를 보여 준다", () => {
  const salesShellSource = readFileSync("components/sales/sales-shell.tsx", "utf8");
  const salesPageSource = readFileSync("app/sales/page.tsx", "utf8");

  assert.match(salesShellSource, /export function SalesLoading/);
  assert.match(
    salesShellSource,
    /if \(!ready \|\| recruitingEnabled === null\) return <SalesLoading \/>;/,
  );
  assert.match(salesPageSource, /import \{ SalesLoading, SalesShell \}/);
  assert.match(salesPageSource, /fallback=\{<SalesLoading \/>\}/);
});

test("프로필을 다시 불러오지 못하면 설계사 영업을 숨기지 않고 재시도를 안내한다", () => {
  const salesShellSource = readFileSync("components/sales/sales-shell.tsx", "utf8");

  assert.match(salesShellSource, /setProfileLoadFailed\(true\)/);
  assert.match(salesShellSource, /다시 불러오기/);
  assert.doesNotMatch(
    salesShellSource,
    /\.catch\(\(\) => \{\s*if \(!cancelled\) setRecruitingEnabled\(false\)/,
  );
});

test("영업 탭은 각 탭이 참조하는 패널을 DOM에 유지한다", () => {
  const salesShellSource = readFileSync("components/sales/sales-shell.tsx", "utf8");

  assert.match(salesShellSource, /visibleTabs\.map\(\(item\) => \{/);
  assert.match(salesShellSource, /hidden=\{!active\}/);
  assert.match(salesShellSource, /id=\{`sales-panel-\$\{item\.key\}`\}/);
});
