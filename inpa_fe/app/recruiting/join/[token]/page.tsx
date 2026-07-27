import { RecruitingJoin } from "@/components/recruiting/recruiting-join";
import { normalizeSignedRouteToken } from "@/lib/signed-route-token";

export default async function RecruitingJoinPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <RecruitingJoin token={normalizeSignedRouteToken(token) ?? ""} />;
}
