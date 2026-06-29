"use client";

// 화법·문구 라이브러리 — 상황별 대본을 복사해 직접 전달(자동발송 없음).
// ★ 카톡(개인 1:1) ⟂ 문자(광고규제) 라벨 + 가드 배너.

import { useState, useEffect, useMemo } from "react";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { getProfile } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { COPY_CATEGORIES, renderCopy, type CopyChannel } from "@/lib/copy-library";

const CHANNEL_BADGE: Record<CopyChannel, { label: string; cls: string }> = {
  kakao: { label: "카톡 · 개인 1:1", cls: "bg-amber-50 text-amber-800 border-amber-200" },
  sms: { label: "문자 · 광고규제", cls: "bg-rose-50 text-rose-700 border-rose-200" },
};

export default function ScriptsPage() {
  const ready = useAuthGuard();
  const [planner, setPlanner] = useState("");
  const [customer, setCustomer] = useState("");
  const [activeKey, setActiveKey] = useState(COPY_CATEGORIES[0].key);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    getProfile().then((p) => setPlanner(p.name?.trim() || "")).catch(() => {});
  }, [ready]);

  const active = useMemo(
    () => COPY_CATEGORIES.find((c) => c.key === activeKey) ?? COPY_CATEGORIES[0],
    [activeKey]
  );

  if (!ready) return null;

  async function handleCopy(id: string, body: string) {
    const ok = await copyText(renderCopy(body, { customer, planner }));
    if (ok) {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 1800);
    }
  }

  return (
    <div className="min-h-dvh">
      <AppNav active="scripts" />
      <main className="mx-auto max-w-5xl px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink">화법 · 문구</h1>
        <p className="mt-1 text-[13px] text-ink3 leading-5">
          상황별 문구를 골라 복사해 고객에게 바로 보내세요. 카톡·문자로 빠르게 전달할 수 있어요.
        </p>

        {/* 치환 입력 — 비우면 '고객'·'담당 설계사'로 들어감 */}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">고객 이름 (선택)</span>
            <input
              value={customer}
              onChange={(e) => setCustomer(e.target.value)}
              placeholder="예: 김민수"
              className="rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-brand"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">내 이름 (설계사)</span>
            <input
              value={planner}
              onChange={(e) => setPlanner(e.target.value)}
              placeholder="예: 홍길동"
              className="rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-brand"
            />
          </label>
        </div>

        {/* 문자(광고) 가드 */}
        <div className="mt-4 rounded-xl border border-amber-300/70 bg-amber-50 px-3.5 py-3">
          <p className="text-[12px] leading-5 text-amber-900">
            <b>수신 동의를 받았거나 거래 관계가 있는 고객에게만</b> 발송하세요. <b>카톡(개인 1:1)</b>은 자유롭게 쓰되,{" "}
            <b>문자로 단체 발송</b>은 광고규제 대상이에요. <b>(광고) 표기 · 무료수신거부 번호 · 야간(21~08시) 발송 금지</b>를 꼭 지키세요.
          </p>
        </div>

        {/* 카테고리 탭 */}
        <div className="mt-5 flex flex-wrap gap-2">
          {COPY_CATEGORIES.map((c) => (
            <button
              key={c.key}
              onClick={() => setActiveKey(c.key)}
              className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition ${
                c.key === activeKey ? "bg-brand-soft text-brand" : "bg-surface2 text-ink2 hover:bg-line"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>

        <p className="mt-3 text-[12px] text-ink3 leading-5">{active.desc}</p>

        {/* 문구 카드 */}
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {active.templates.map((t) => {
            const badge = CHANNEL_BADGE[t.channel];
            const preview = renderCopy(t.body, { customer, planner });
            return (
              <Card key={t.id} className="p-4 flex flex-col">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-[14px] font-bold text-ink">{t.title}</h3>
                  <span className={`shrink-0 text-[10px] font-semibold rounded-full border px-2 py-0.5 ${badge.cls}`}>
                    {badge.label}
                  </span>
                </div>
                <p className="mt-2 flex-1 whitespace-pre-wrap text-[13px] leading-6 text-ink2">{preview}</p>
                <button
                  onClick={() => handleCopy(t.id, t.body)}
                  className="mt-3 self-start rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 active:scale-[0.98] transition"
                >
                  {copiedId === t.id ? "복사됨 ✓" : "복사"}
                </button>
              </Card>
            );
          })}
        </div>
      </main>
    </div>
  );
}
