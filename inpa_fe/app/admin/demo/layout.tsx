"use client";

// 목업 데모 레이아웃 — 관리자 전용. 상단 "데모" 배지 + 화면 간 서브탭.
// 모든 데모 페이지는 lib/mock 데이터만 사용(실 API 호출 없음).

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAdminGuard } from "@/lib/useAdminGuard";

const SUB = [
  { href: "/admin/demo", label: "개요" },
  { href: "/admin/demo/dashboard", label: "대시보드" },
  { href: "/admin/demo/customers", label: "고객" },
  { href: "/admin/demo/analysis", label: "보장분석" },
  { href: "/admin/demo/compare", label: "증권 비교" },
  { href: "/admin/demo/share", label: "고객 공유뷰" },
];

export default function DemoLayout({ children }: { children: React.ReactNode }) {
  const ready = useAdminGuard();
  const pathname = usePathname();
  if (!ready) return null;
  return (
    // 데모는 전용 크롬(풀블리드 배지 바 + 서브탭 + 자체 컨테이너)을 유지한다.
    // 셸(main)의 새 패딩을 상쇄해 기존 화면과 동일하게 보이도록 음수 마진을 준다.
    <div className="-m-4 sm:-m-6">
      <div className="sticky top-0 z-20 bg-amber-50 border-b border-amber-200 px-4 sm:px-6 py-2 flex items-center gap-2 flex-wrap">
        <span className="text-[12px] font-bold text-amber-900 bg-amber-200 rounded-full px-2.5 py-0.5">🧪 목업 데모</span>
        <span className="text-[12px] text-amber-800">실제 데이터가 아니에요. 데이터가 채워지면 이런 형식·UI라는 미리보기입니다.</span>
      </div>
      <nav className="border-b border-line bg-surface px-2 sm:px-4 flex gap-1 overflow-x-auto">
        {SUB.map((s) => {
          const active = s.href === "/admin/demo" ? pathname === s.href : pathname.startsWith(s.href);
          return (
            <Link
              key={s.href}
              href={s.href}
              className={`px-3 py-2.5 text-[13px] font-semibold whitespace-nowrap border-b-2 transition ${
                active ? "border-brand text-brand" : "border-transparent text-ink2 hover:text-ink"
              }`}
            >
              {s.label}
            </Link>
          );
        })}
      </nav>
      <div className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">{children}</div>
    </div>
  );
}
