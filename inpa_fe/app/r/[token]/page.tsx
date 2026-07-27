import { PublicRecruitingApplication } from "@/components/recruiting/public-recruiting-application";
import { normalizeSignedRouteToken } from "@/lib/signed-route-token";

export default async function PublicRecruitingPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <PublicRecruitingApplication token={normalizeSignedRouteToken(token) ?? ""} />;
}
