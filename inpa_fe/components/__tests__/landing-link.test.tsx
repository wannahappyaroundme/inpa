import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { BrandLandingProvider, LandingLink } from "@/components/landing-link";

it("이야기 가입 링크는 기존 유입값을 지키고 비어 있는 값만 채운다", () => {
  render(
    <BrandLandingProvider
      appBase=""
      utmSearch="?utm_source=old_link&utm_medium=redirect&utm_content=hero&utm_term=planner"
      utmDefaults={{
        utm_source: "www_inpa_kr",
        utm_medium: "brand_story",
        utm_campaign: "cinema",
      }}
    >
      <LandingLink href="/register">가입</LandingLink>
      <LandingLink href="/blog">블로그</LandingLink>
    </BrandLandingProvider>,
  );

  expect(screen.getByRole("link", { name: "가입" })).toHaveAttribute(
    "href",
    "/register?utm_source=old_link&utm_medium=redirect&utm_content=hero&utm_term=planner&utm_campaign=cinema",
  );
  expect(screen.getByRole("link", { name: "블로그" })).toHaveAttribute("href", "/blog");
});
