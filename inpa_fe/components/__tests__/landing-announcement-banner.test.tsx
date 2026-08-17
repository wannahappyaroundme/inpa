import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import {
  CONSULTATION_BANNER_STORAGE_KEY,
  LandingAnnouncementBanner,
} from "@/components/landing-announcement-banner";

const HEADLINE = "상담 녹음과 AI 핵심 메모가 열렸어요.";
const DETAIL = "상담을 마치면 핵심 내용이 메모로 정리됩니다.";
const A_DAY_MS = 24 * 60 * 60 * 1000;
/** 다음 공지로 재사용하는 상황을 흉내 내는 저장 키(비밀값 아님). */
const OTHER_BANNER_STORAGE_KEY = "inpa_banner_other_v1"; // gitleaks:allow

describe("랜딩 상단 새 기능 공지", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("새 기능 문구와 가입 링크를 보여 준다", () => {
    render(<LandingAnnouncementBanner />);

    expect(screen.getByText("NEW")).toBeInTheDocument();
    expect(screen.getByText(HEADLINE)).toBeInTheDocument();
    expect(screen.getByText(DETAIL)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "무료로 시작하기" })).toHaveAttribute(
      "href",
      "/register",
    );
  });

  it("닫기를 누르면 공지가 사라지고 이번 방문 동안 숨김으로 기록한다", async () => {
    const user = userEvent.setup();
    render(<LandingAnnouncementBanner />);

    await user.click(screen.getByRole("button", { name: "공지 닫기" }));

    expect(screen.queryByText(HEADLINE)).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem(CONSULTATION_BANNER_STORAGE_KEY)).toBeTruthy();
    expect(window.localStorage.getItem(CONSULTATION_BANNER_STORAGE_KEY)).toBeNull();
  });

  it("24시간 동안 보지 않기를 누르면 하루 뒤 만료 시각을 저장한다", async () => {
    const user = userEvent.setup();
    const clickedAt = Date.now();
    render(<LandingAnnouncementBanner />);

    await user.click(screen.getByRole("button", { name: "24시간 동안 보지 않기" }));

    expect(screen.queryByText(HEADLINE)).not.toBeInTheDocument();
    const until = Number(window.localStorage.getItem(CONSULTATION_BANNER_STORAGE_KEY));
    expect(until).toBeGreaterThan(Date.now());
    expect(until).toBeGreaterThanOrEqual(clickedAt + A_DAY_MS);
    expect(until).toBeLessThanOrEqual(Date.now() + A_DAY_MS);
  });

  it("숨김 기간이 남아 있으면 공지를 그리지 않는다", () => {
    window.localStorage.setItem(
      CONSULTATION_BANNER_STORAGE_KEY,
      String(Date.now() + 60 * 60 * 1000),
    );

    const { container } = render(<LandingAnnouncementBanner />);

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(HEADLINE)).not.toBeInTheDocument();
  });

  it("숨김 기간이 지났으면 공지를 다시 보여 준다", () => {
    window.localStorage.setItem(
      CONSULTATION_BANNER_STORAGE_KEY,
      String(Date.now() - 60 * 1000),
    );

    render(<LandingAnnouncementBanner />);

    expect(screen.getByText(HEADLINE)).toBeInTheDocument();
  });

  it("다른 공지로 재사용할 수 있게 저장 키와 문구, 링크를 받는다", () => {
    window.localStorage.setItem(
      CONSULTATION_BANNER_STORAGE_KEY,
      String(Date.now() + A_DAY_MS),
    );

    render(
      <LandingAnnouncementBanner
        storageKey={OTHER_BANNER_STORAGE_KEY}
        headline="새 소식이 도착했어요."
        detail="자세한 내용을 확인해보세요."
        ctaLabel="자세히 보기"
        ctaHref="/blog"
      />,
    );

    expect(screen.getByText("새 소식이 도착했어요.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "자세히 보기" })).toHaveAttribute("href", "/blog");
  });
});
