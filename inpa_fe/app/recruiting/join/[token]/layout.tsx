import type { Metadata } from "next";
import type { ReactNode } from "react";

import { publicTokenMetadata } from "@/lib/public-og";

export const metadata: Metadata = publicTokenMetadata(
  "설계사 팀 합류 | 인파",
  "리더 정보를 확인하고 인파에서 함께 일할 흐름을 이어가세요.",
);

export default function RecruitingJoinLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
