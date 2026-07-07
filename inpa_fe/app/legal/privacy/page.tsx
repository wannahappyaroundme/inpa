// 개인정보처리방침 (PP-v1) — 정본: docs/dev/16-legal-and-consent.md §3.
// 한국 개인정보보호법(PIPA) 기준. CPO = 황예진, 운영사 (주)서울엘엔에스금융컨설팅 (2026-07-07 확정).
import { LegalPage, Article, LegalTable } from "@/components/legal";

export const metadata = { title: "개인정보처리방침" };

const Li = ({ children }: { children: React.ReactNode }) => <li className="ml-1">{children}</li>;

export default function PrivacyPage() {
  return (
    <LegalPage title="개인정보처리방침" effective="버전 PP-v1 · 운영 (주)서울엘엔에스금융컨설팅(브랜드: 핀고) · 시행일 2026-07-07 · 한국 개인정보보호법(PIPA)·정보통신망법 기준.">
      <Article n={1} title="수집하는 개인정보">
        <p className="font-semibold text-[var(--ink)]">가. 설계사(이용자) 정보</p>
        <LegalTable
          head={["항목", "수집 방법", "보유 기간"]}
          rows={[
            ["이메일 주소", "회원가입", "탈퇴 후 30일"],
            ["비밀번호(암호화)", "회원가입", "탈퇴 후 즉시 파기"],
            ["소속(원수사/GA명)", "온보딩", "탈퇴 후 30일"],
            ["모집 자격 자기신고 여부", "온보딩", "탈퇴 후 30일"],
            ["서비스 이용 기록", "자동 수집", "1년"],
            ["IP 주소(동의 기록용)", "동의 시 자동 수집", "동의 철회 후 5년"],
          ]}
        />
        <p className="mt-3 font-semibold text-[var(--ink)]">나. 고객 정보 (설계사가 입력)</p>
        <LegalTable
          head={["항목", "민감정보 여부", "이용 목적"]}
          rows={[
            ["고객명", "아니오", "담보 분석·공유"],
            ["생년·성별·연락처", "아니오", "담보 계산·연락"],
            ["직업위험등급", "아니오", "손해보험 분석"],
            [<><b>병력(질병명·진단 이력)</b></>, <><b>예(민감정보)</b></>, "Claude AI API 분석(국외이전 포함)"],
          ]}
        />
        <p className="mt-2 text-[13px]">
          ※ 병력은 개인정보보호법 제23조의 <b>민감정보</b>입니다. 수집·처리 시 별도 명시적 동의가 필요하며,
          Claude API(Anthropic Inc., 미국)로 전송되는 국외이전에 대한 동의도 별도로 받아야 합니다(제4조).
          셀프진단(잠재고객 본인 진단)에서는 병력을 수집하지 않습니다.
        </p>
      </Article>

      <Article n={2} title="개인정보 처리 목적">
        <ol className="list-decimal pl-5 space-y-1">
          <Li><b>설계사 서비스 제공</b>: 계정 관리, 고객 데이터 분석, 담보 시각화</Li>
          <Li><b>AI 분석</b>: 보험증권 텍스트 추출·담보 정규화, 히트맵 생성(Claude API 이용)</Li>
          <Li><b>서비스 개선</b>: 담보명 정규화 사전 학습(익명화된 매핑 데이터 활용)</Li>
          <Li><b>공지·고객지원</b>: 공지사항 발송, 1:1 문의 응대</Li>
        </ol>
        <p className="mt-1"><b>인파는 고객 정보를 마케팅·제3자 제공에 사용하지 않습니다.</b></p>
      </Article>

      <Article n={3} title="개인정보 보유 및 파기">
        <LegalTable
          head={["정보 유형", "보유 기간", "파기 방법"]}
          rows={[
            ["설계사 계정", "탈퇴 후 30일", "DB 익명화"],
            ["고객 개인정보(병력 제외)", "설계사 탈퇴 후 30일", "DB 삭제"],
            ["상담으로 이어지지 않은 보장점검·상담 신청 정보", "마지막 활동일부터 6개월", "자동 파기(DB 삭제)"],
            ["병력(민감정보)", "동의 철회 또는 설계사 탈퇴 후 즉시", "DB 삭제 + 로그 파기"],
            ["동의 기록(ConsentLog)", "5년", "보관 후 파기"],
            ["이용 로그", "1년", "자동 삭제"],
            ["결제 기록", "5년(전자상거래법 §6)", "별도 보관"],
          ]}
        />
      </Article>

      <Article n={4} title="민감정보(병력) 및 국외이전">
        <p className="font-semibold text-[var(--ink)]">4.1 처리 근거</p>
        <p>고객의 병력은 개인정보보호법 제23조의 민감정보입니다. 인파는 ①고객의 별도 명시적 동의(설계사가 서비스 내 동의서 화면을 통해 직접 수집) ②동의 내용에 처리 목적·항목·보유기간 명시, 요건을 충족한 경우에만 병력을 처리합니다.</p>
        <p className="mt-3 font-semibold text-[var(--ink)]">4.2 국외이전</p>
        <p>병력을 포함한 보험증권 분석 정보는 <b>Claude API(Anthropic Inc., 미국 소재)</b>에 전송됩니다.</p>
        <LegalTable
          head={["항목", "내용"]}
          rows={[
            ["수신자", "Anthropic, Inc."],
            ["소재 국가", "미국 (United States)"],
            ["전송 목적", "보험증권 텍스트 추출 및 담보 분석 AI 처리"],
            ["전송 항목", "증권 텍스트(병력 포함 가능)"],
            ["전송 시점·방법", "분석 요청 시 HTTPS 전송"],
            ["보유 기간", "Anthropic의 데이터 처리·보관 정책에 따름"],
          ]}
        />
        <p className="mt-2 text-[13px]">
          Anthropic 데이터 보호 정책: <a href="https://www.anthropic.com/legal/privacy" target="_blank" rel="noopener noreferrer" className="text-[var(--brand)] underline">anthropic.com/legal/privacy</a>.
          Anthropic은 API로 전송된 데이터를 <b>모델 학습에 사용하지 않습니다</b>(API 기본 정책). 구체적 보관 기간은 Anthropic 정책을 따릅니다.
        </p>
        <p className="mt-3 font-semibold text-[var(--ink)]">4.3 동의 게이트</p>
        <p>병력 국외이전 동의가 없으면 AI 분석 기능이 <b>시스템적으로 차단</b>됩니다(동의 전 분석 요청은 거부됩니다).</p>
      </Article>

      <Article n={5} title="개인정보 처리 수탁자">
        <LegalTable
          head={["수탁자", "위탁 업무", "보유·이용 기간"]}
          rows={[
            ["Anthropic, Inc. (미국)", "AI 텍스트 분석(병력 포함 가능)", "Anthropic 정책에 따름"],
            ["Render, Inc. (미국)", "백엔드 서버 호스팅", "계약 기간"],
            ["Neon, Inc. (미국)", "데이터베이스 호스팅", "계약 기간"],
            ["Vercel, Inc. (미국)", "프론트엔드 호스팅·방문자 통계", "계약 기간"],
            ["Cloudflare, Inc. (미국)", "업로드 이미지(명함·프로필 사진) 저장(R2)", "계약 기간"],
            ["Resend, Inc. (미국)", "가입·비밀번호 등 메일 발송", "계약 기간"],
          ]}
        />
      </Article>

      <Article n={6} title="정보주체 권리">
        <LegalTable
          head={["권리", "행사 방법", "처리 기한"]}
          rows={[
            ["열람", "이메일 신청", "10일 이내"],
            ["정정", "서비스 내 직접 수정 또는 이메일 신청", "10일 이내"],
            ["삭제(잊혀질 권리)", "이메일 신청", "10일 이내"],
            ["처리정지", "이메일 신청", "10일 이내"],
            ["동의철회", "서비스 내 동의철회 또는 이메일 신청", "즉시 처리"],
          ]}
        />
        <p className="mt-2 text-[13px]">동의 철회 시 관련 기능(AI 분석)은 즉시 중단되며, 이미 처리된 데이터는 법령 허용 범위 내에서 삭제 처리합니다.</p>
      </Article>

      <Article n={7} title="개인정보 보호책임자(CPO)">
        <ul className="list-disc pl-6 space-y-0.5">
          <Li>운영: (주)서울엘엔에스금융컨설팅 (브랜드: 핀고/Fingo) · 대표자 황희철</Li>
          <Li>사업자등록번호: 109-86-17632 · 통신판매업신고: 2021-서울구로-1990</Li>
          <Li>주소: 서울특별시 금천구 서부샛길 606, A동 24층 2409호(가산동, 대성디폴리스지식산업센터) (우편번호 08504)</Li>
          <Li><b>개인정보 보호책임자: 황예진 (hello.fingo.official@gmail.com)</b></Li>
          <Li>개인정보 관련 문의: hello.fingo.official@gmail.com 또는 서비스 내 1:1 문의</Li>
        </ul>
        <p className="mt-1 text-[13px]">개인정보 침해에 대한 신고·상담은 개인정보침해신고센터(118), 대검찰청·경찰청 사이버수사 등에 문의할 수 있습니다.</p>
      </Article>

      <Article title="고지 의무">
        <p>본 방침의 내용 추가·삭제·수정이 있을 경우 시행 7일 전부터 서비스 공지사항을 통해 고지합니다.</p>
      </Article>
    </LegalPage>
  );
}
