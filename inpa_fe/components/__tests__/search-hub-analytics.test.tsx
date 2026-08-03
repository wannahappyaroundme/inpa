import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const analytics = vi.hoisted(() => ({ track: vi.fn() }));
vi.mock("@vercel/analytics", () => ({ track: analytics.track }));

import {
  SearchHubViewTracker,
  TrackedSearchHubCta,
  trackSearchHubEvent,
} from "@/components/search-hub-analytics";

beforeEach(() => analytics.track.mockReset());

describe("검색 허브 개인정보 안전 이벤트", () => {
  it("허브 노출과 가입 CTA에 고정 kind와 slug만 전송한다", () => {
    render(
      <>
        <SearchHubViewTracker kind="solution" slug="policy-analysis" />
        <TrackedSearchHubCta kind="solution" slug="policy-analysis" href="#register">
          시작하기
        </TrackedSearchHubCta>
      </>,
    );

    expect(analytics.track).toHaveBeenCalledWith("search_hub_view", {
      hub_kind: "solution",
      hub_slug: "policy-analysis",
    });
    fireEvent.click(screen.getByRole("link", { name: "시작하기" }));
    expect(analytics.track).toHaveBeenLastCalledWith("search_hub_cta_click", {
      hub_kind: "solution",
      hub_slug: "policy-analysis",
    });
    expect(Object.keys(analytics.track.mock.calls[0][1]).sort()).toEqual(["hub_kind", "hub_slug"]);
    expect(JSON.stringify(analytics.track.mock.calls)).not.toMatch(/url|query|referrer|customer/i);
  });

  it("목록에 없는 kind와 slug를 런타임에서 버린다", () => {
    trackSearchHubEvent("view", "private-kind" as never, "customer-secret" as never);
    trackSearchHubEvent("click", "guide", "private-slug" as never);

    expect(analytics.track).not.toHaveBeenCalled();
  });
});
