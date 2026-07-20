import { redirect } from "next/navigation";

import { normalizeRecruitingTab } from "@/components/recruiting/recruiting-view-model";

export default async function RecruitingPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>;
}) {
  const params = await searchParams;
  const view = normalizeRecruitingTab(params.tab ?? null);
  redirect(`/sales?tab=recruiting&view=${view}`);
}
