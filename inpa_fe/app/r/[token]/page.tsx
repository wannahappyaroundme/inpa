import { PublicRecruitingApplication } from "@/components/recruiting/public-recruiting-application";

export default async function PublicRecruitingPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <PublicRecruitingApplication token={token} />;
}
