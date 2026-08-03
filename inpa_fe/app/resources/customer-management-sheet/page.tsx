import { CustomerManagementSheet } from "@/components/customer-management-sheet";
import {
  PublicResourcePage,
  publicResourceMetadata,
} from "@/components/public-resource-page";

const PATH = "/resources/customer-management-sheet";
const TITLE = "보험설계사 고객 관리표, 빈 CSV 양식 내려받기";
const DESCRIPTION = "고객명, 연락처, 영업 단계, 진행 상태, 마지막 연락일, 다음 행동과 메모를 기록하는 빈 고객 관리 CSV 양식입니다.";

export const metadata = publicResourceMetadata({ title: TITLE, description: DESCRIPTION, path: PATH });

export default function CustomerManagementSheetPage() {
  return (
    <PublicResourcePage
      kindLabel="무료 실무 자료"
      title={TITLE}
      description={DESCRIPTION}
      answer="고객 기록을 처음 정리할 때 필요한 7개 항목만 담은 빈 관리표입니다. 샘플 고객 없이 제목 행만 내려받아 내 업무 방식에 맞게 채울 수 있습니다."
      path={PATH}
      updatedAt="2026-08-04"
      privacyNote="빈 양식만 브라우저에서 만들며 고객 정보는 저장하거나 서버로 전송하지 않아요. 내려받은 뒤 내 기기에서 직접 작성해 주세요."
      related={[
        { href: "/solutions/customer-management", label: "보험설계사 고객 관리 흐름 보기" },
        { href: "/guides/customer-follow-up", label: "고객 후속 연락 관리 순서 보기" },
      ]}
    >
      <CustomerManagementSheet />
    </PublicResourcePage>
  );
}
