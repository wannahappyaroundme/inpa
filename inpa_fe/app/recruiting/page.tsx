import { Suspense } from "react";

import { RecruitingLoading } from "@/components/recruiting/recruiting-states";
import { RecruitingShell } from "@/components/recruiting/recruiting-shell";

export default function RecruitingPage() {
  return (
    <Suspense fallback={<RecruitingLoading fullPage />}>
      <RecruitingShell />
    </Suspense>
  );
}
