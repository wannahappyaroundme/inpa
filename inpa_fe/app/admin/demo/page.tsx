import Link from "next/link";
import { Card } from "@/components/ui";

// 목업 데모 개요 — 각 화면으로 이동.
const SCREENS = [
  { href: "/admin/demo/dashboard", emoji: "🏠", title: "대시보드", desc: "KPI·캘린더·오늘 일정이 채워진 설계사 홈" },
  { href: "/admin/demo/customers", emoji: "👥", title: "고객 목록(CRM)", desc: "고객 카드·만기 배지·계약 수가 채워진 목록" },
  { href: "/admin/demo/analysis", emoji: "🗂️", title: "보장분석 히트맵", desc: "담보 카테고리별 3색(넉넉/적정/부족/없음) 한눈표" },
  { href: "/admin/demo/compare", emoji: "🔁", title: "비교 분석", desc: "기존 증권 vs 제안 증권 담보·보험료 비교 + 유의사항" },
  { href: "/admin/demo/share", emoji: "🔗", title: "고객 공유뷰", desc: "고객이 받는 화면. 납입 현황·보장 목록(사실만)" },
];

export default function DemoIndex() {
  return (
    <div>
      <h1 className="text-[22px] font-extrabold text-ink">목업 데모 화면</h1>
      <p className="mt-2 text-[14px] text-ink2 leading-6">
        실제 운영 데이터가 아닌 <b>예시 데이터</b>로 각 화면이 채워졌을 때의 형식·UI를 보여줍니다.
        투자자·동료·디자인 검토용 미리보기예요. 실제 페이지는 로그인 후 각 메뉴에서 실데이터로 동작합니다.
      </p>
      <div className="mt-5 grid sm:grid-cols-2 gap-4">
        {SCREENS.map((s) => (
          <Link key={s.href} href={s.href}>
            <Card className="p-4 hover:border-brand transition h-full">
              <div className="flex items-start gap-3">
                <span className="text-[22px]">{s.emoji}</span>
                <div>
                  <div className="text-[15px] font-bold text-ink">{s.title} ›</div>
                  <div className="text-[13px] text-ink3 mt-0.5 leading-5">{s.desc}</div>
                </div>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
