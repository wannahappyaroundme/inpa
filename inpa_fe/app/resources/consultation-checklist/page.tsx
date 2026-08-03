import { ConsultationChecklist } from "@/components/consultation-checklist";
import {
  PublicResourcePage,
  publicResourceMetadata,
} from "@/components/public-resource-page";

const PATH = "/resources/consultation-checklist";
const TITLE = "보험 첫 상담 체크리스트, 준비부터 후속 연락까지";
const DESCRIPTION = "보험 첫 상담 전 준비, 상담 중 확인, 상담 후 정리를 화면에서 체크하고 인쇄할 수 있는 무료 실무 체크리스트입니다.";

export const metadata = publicResourceMetadata({ title: TITLE, description: DESCRIPTION, path: PATH });

export default function ConsultationChecklistPage() {
  return (
    <PublicResourcePage
      kindLabel="무료 실무 자료"
      title={TITLE}
      description={DESCRIPTION}
      answer="첫 상담에서 확인할 내용을 상담 전, 상담 중, 상담 후 세 구간으로 나눴습니다. 화면에서 바로 체크하거나 종이로 인쇄해 상담 순서를 정리할 수 있습니다."
      path={PATH}
      updatedAt="2026-08-04"
      privacyNote="체크한 내용은 이 화면에서만 표시되며 저장되거나 서버로 전송되지 않아요. 화면을 닫거나 새로 열면 체크가 초기화됩니다."
      related={[
        { href: "/guides/first-consultation", label: "첫 상담 준비 순서 자세히 보기" },
        { href: "/solutions/sales-management", label: "첫 연락부터 미팅까지 영업 흐름 보기" },
      ]}
    >
      <ConsultationChecklist />
    </PublicResourcePage>
  );
}
