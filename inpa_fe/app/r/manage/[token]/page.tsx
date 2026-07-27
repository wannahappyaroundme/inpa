import { PublicRecruitingManageView } from "@/components/recruiting/public-recruiting-manage";
import { normalizeSignedRouteToken } from "@/lib/signed-route-token";

export default async function RecruitingManagePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <PublicRecruitingManageView token={normalizeSignedRouteToken(token) ?? ""} />;
}
