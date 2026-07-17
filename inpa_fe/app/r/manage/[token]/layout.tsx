import type { Metadata } from "next";
import type { ReactNode } from "react";

import { publicTokenMetadata } from "@/lib/public-og";

export const metadata: Metadata = publicTokenMetadata(
  "설계사 지원 상태 | 인파",
  "내 설계사 동료 지원 상태와 연락 여부를 확인해보세요.",
);

export default function RecruitingManageLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
