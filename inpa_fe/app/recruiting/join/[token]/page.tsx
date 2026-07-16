import { RecruitingJoin } from "@/components/recruiting/recruiting-join";

export default async function RecruitingJoinPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <RecruitingJoin token={token} />;
}
