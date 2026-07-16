"use client";

import { PUBLIC_PRIMARY_BUTTON, PublicRecruitingNotice } from "@/components/recruiting/public-recruiting-ui";

export default function RecruitingManageError({ unstable_retry }: { unstable_retry: () => void }) {
  return (
    <PublicRecruitingNotice
      role="alert"
      title="지원 상태를 다시 열면 이어서 확인할 수 있어요."
      description="연결을 확인한 뒤 다시 시도해주세요."
      action={<button type="button" onClick={unstable_retry} className={PUBLIC_PRIMARY_BUTTON}>상태 다시 열기</button>}
    />
  );
}
