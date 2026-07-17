"use client";

import { PUBLIC_PRIMARY_BUTTON, PublicRecruitingNotice } from "@/components/recruiting/public-recruiting-ui";

export default function RecruitingJoinError({ unstable_retry }: { unstable_retry: () => void }) {
  return (
    <PublicRecruitingNotice
      role="alert"
      title="합류 화면을 다시 열면 이어갈 수 있어요."
      description="연결을 확인한 뒤 다시 시도해주세요."
      action={<button type="button" onClick={unstable_retry} className={PUBLIC_PRIMARY_BUTTON}>화면 다시 열기</button>}
    />
  );
}
