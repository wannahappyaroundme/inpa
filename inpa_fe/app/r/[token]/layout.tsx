import type { Metadata } from "next";
import type { ReactNode } from "react";

import { publicTokenMetadata } from "@/lib/public-og";

export const metadata: Metadata = publicTokenMetadata(
  "설계사 동료 지원 | 인파",
  "함께 일할 설계사 동료와 먼저 편하게 이야기 나눠보세요.",
);

export default function PublicRecruitingLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
