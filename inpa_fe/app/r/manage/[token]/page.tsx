import { PublicRecruitingManageView } from "@/components/recruiting/public-recruiting-manage";

export default async function RecruitingManagePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <PublicRecruitingManageView token={token} />;
}
