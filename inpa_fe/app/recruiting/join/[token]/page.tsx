import { RecruitingJoin } from "@/components/recruiting/recruiting-join";
import { normalizeRecruitingRouteToken } from "@/components/recruiting/public-recruiting-view-model";

export default async function RecruitingJoinPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <RecruitingJoin token={normalizeRecruitingRouteToken(token) ?? ""} />;
}
