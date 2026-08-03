import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  SEARCH_HUBS,
  SEARCH_HUB_CTA_PATH,
  getSearchHub,
  getSearchHubPaths,
} from "@/lib/search-content";

const EXPECTED_PATHS = [
  "/solutions/customer-management",
  "/solutions/policy-analysis",
  "/solutions/sales-management",
  "/guides/first-consultation",
  "/guides/customer-follow-up",
  "/guides/policy-review",
  "/guides/factual-comparison",
] as const;

describe("검색 근거 원고 manifest", () => {
  it("솔루션 3개와 실무 가이드 4개를 정확한 경로로 제공한다", () => {
    expect(SEARCH_HUBS).toHaveLength(7);
    expect(SEARCH_HUBS.filter((hub) => hub.kind === "solution")).toHaveLength(3);
    expect(SEARCH_HUBS.filter((hub) => hub.kind === "guide")).toHaveLength(4);
    expect(getSearchHubPaths()).toEqual(EXPECTED_PATHS);
    expect(SEARCH_HUB_CTA_PATH).toBe("/register");
  });

  it("slug, 경로, 제목이 중복되지 않고 종류가 다른 slug는 조회하지 않는다", () => {
    const slugs = SEARCH_HUBS.map((hub) => hub.slug);
    const paths = getSearchHubPaths();
    const titles = SEARCH_HUBS.map((hub) => hub.title);

    expect(new Set(slugs).size).toBe(slugs.length);
    expect(new Set(paths).size).toBe(paths.length);
    expect(new Set(titles).size).toBe(titles.length);

    for (const hub of SEARCH_HUBS) {
      expect(getSearchHub(hub.kind, hub.slug)).toBe(hub);
      expect(getSearchHub(hub.kind === "solution" ? "guide" : "solution", hub.slug)).toBeUndefined();
    }
  });

  it("각 원고가 답, 현장 순서, 실제 화면, 확인표, 한계와 FAQ를 갖춘다", () => {
    for (const hub of SEARCH_HUBS) {
      expect(hub.description.length).toBeGreaterThanOrEqual(45);
      expect(hub.answer.length).toBeGreaterThanOrEqual(55);
      expect(hub.fitFor.length).toBeGreaterThanOrEqual(3);
      expect(hub.steps.length).toBeGreaterThanOrEqual(3);
      expect(hub.checklist.length).toBeGreaterThanOrEqual(4);
      expect(hub.limitations.length).toBeGreaterThanOrEqual(2);
      expect(hub.faq.length).toBeGreaterThanOrEqual(3);
      expect(hub.evidence.length).toBeGreaterThanOrEqual(1);

      for (const evidence of hub.evidence) {
        expect(evidence.src).toMatch(/^\/landing-test\/(customers|coverage|compare|dashboard|schedule)\.webp$/);
        expect(evidence.alt.trim().length).toBeGreaterThan(12);
        expect(evidence.caption.trim().length).toBeGreaterThan(20);
        expect(existsSync(join(process.cwd(), "public", evidence.src))).toBe(true);
      }
    }
  });

  it("관련 경로는 공개 페이지 또는 같은 manifest 안의 페이지로만 연결한다", () => {
    const allowed = new Set([
      ...EXPECTED_PATHS,
      "/",
      "/blog",
      "/faq",
      "/data-policy",
    ]);

    for (const hub of SEARCH_HUBS) {
      expect(hub.relatedPaths.length).toBeGreaterThanOrEqual(2);
      for (const path of hub.relatedPaths) expect(allowed.has(path as never)).toBe(true);
    }
  });

  it("사용자 문구 금칙어와 제공하지 않는 자동 발송·선택 권장 주장을 막는다", () => {
    const renderedCopy = JSON.stringify(SEARCH_HUBS);

    expect(renderedCopy).not.toContain(String.fromCodePoint(0x2014));
    expect(renderedCopy).not.toMatch(/준비\s?중|§/);
    expect(renderedCopy).not.toMatch(/자동\s*(문자|메시지|발송)|문자를\s*자동|메시지를\s*자동/);
    expect(renderedCopy).not.toMatch(/상품\s*추천|가입\s*추천|어느\s*쪽이\s*(더\s*)?(좋|유리)/);
    expect(renderedCopy).not.toMatch(/무조건|확실한|보장됩니다|심의\s*완료/);
  });

  it("업데이트 날짜는 검증 가능한 고정 형식을 쓴다", () => {
    for (const hub of SEARCH_HUBS) {
      expect(hub.updatedAt).toMatch(/^2026-08-0[34]$/);
    }
  });
});
