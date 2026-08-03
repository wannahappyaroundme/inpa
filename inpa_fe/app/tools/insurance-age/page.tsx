import { InsuranceAgeCalculator } from "@/components/insurance-age-calculator";
import {
  PublicResourcePage,
  publicResourceMetadata,
} from "@/components/public-resource-page";

const PATH = "/tools/insurance-age";
const TITLE = "보험나이 계산기, 생년월일로 바로 확인하기";
const DESCRIPTION = "생년월일과 기준일을 입력해 보험나이를 확인하는 무료 계산기입니다. 입력한 날짜는 저장하거나 서버로 보내지 않습니다.";

export const metadata = publicResourceMetadata({ title: TITLE, description: DESCRIPTION, path: PATH });

export default function InsuranceAgePage() {
  return (
    <PublicResourcePage
      kindLabel="무료 실무 도구"
      title={TITLE}
      description={DESCRIPTION}
      answer="생년월일과 기준일을 넣으면 만나이를 기준으로 마지막 생일부터 6개월이 지났는지 확인해 보험나이를 계산합니다. 날짜는 브라우저 안에서만 계산합니다."
      path={PATH}
      updatedAt="2026-08-04"
      privacyNote="입력한 생년월일과 기준일은 이 화면에서만 계산되며 저장되거나 서버로 전송되지 않아요."
      related={[
        { href: "/solutions/customer-management", label: "보험설계사 고객 관리 흐름 보기" },
        { href: "/guides/first-consultation", label: "보험 첫 상담 준비 체크리스트 보기" },
      ]}
    >
      <InsuranceAgeCalculator />
    </PublicResourcePage>
  );
}
