"use client";

// 계정·모드 설정 — 위촉 형태(전속/GA), 관리직 KPI 공유, 익명 코호트 동의.
// updateProfile(PATCH /auth/profile/) 로 저장. 동의는 모두 기본 거부(opt-in).

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { AccountSecurity } from "@/components/account-security";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { getProfile, updateProfile, getGoogleCalendarConnectUrl, disconnectGoogleCalendar, logout, type ProfileResponse } from "@/lib/api";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

export default function AccountSettingsPage() {
  const ready = useAuthGuard();
  const router = useRouter();
  const [p, setP] = useState<ProfileResponse | null>(null);
  const [managerEmail, setManagerEmail] = useState("");
  const [introText, setIntroText] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    getProfile().then((res) => {
      setP(res);
      setManagerEmail(res.manager_email ?? "");
      setIntroText(res.intro_text ?? "");
    }).catch(() => { /* useAuthGuard 처리 */ });
  }, [ready]);

  // 구글 캘린더 연동 콜백 결과(?gcal=) 배너 처리 후 URL 정리.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const g = new URLSearchParams(window.location.search).get("gcal");
    if (!g) return;
    if (g === "connected") setMsg("구글 캘린더가 연동되었어요");
    else if (g === "denied") setMsg("구글 연동을 취소했어요");
    else setMsg("구글 캘린더 연동에 실패했어요. 다시 시도해 주세요.");
    window.history.replaceState({}, "", "/settings/account");
    setTimeout(() => setMsg(null), 2500);
  }, []);

  async function connectGoogleCalendar() {
    try {
      const { auth_url } = await getGoogleCalendarConnectUrl();
      window.location.href = auth_url;
    } catch {
      setMsg("연동 시작에 실패했어요.");
    }
  }

  async function disconnectGcal() {
    setSaving(true);
    try {
      await disconnectGoogleCalendar();
      const res = await getProfile();
      setP(res);
      setMsg("구글 캘린더 연동을 해제했어요");
      setTimeout(() => setMsg(null), 1800);
    } catch {
      setMsg("해제 실패");
    } finally {
      setSaving(false);
    }
  }

  async function patch(payload: Parameters<typeof updateProfile>[0], note: string) {
    setSaving(true);
    setMsg(null);
    try {
      const res = await updateProfile(payload);
      setP(res);
      setManagerEmail(res.manager_email ?? "");
      setMsg(note);
      setTimeout(() => setMsg(null), 1800);
    } catch {
      setMsg("저장 실패");
    } finally {
      setSaving(false);
    }
  }

  if (!ready || !p) return null;

  return (
    <div className="min-h-dvh">
      <AppNav active="settings" />
      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        <h1 className="text-[22px] font-extrabold text-ink">계정 · 모드 설정</h1>
        {msg && (
          <div className="mt-4 rounded-xl border border-line bg-success-tint px-4 py-2 text-[13px] text-success">{msg}</div>
        )}

        <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {/* 위촉 형태 */}
        <Card className="px-5 py-4">
          <div className="text-[15px] font-bold text-ink">위촉 형태</div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            전속(원수사)은 타사 비교 분석 대신 <b>자사 보장공백</b> 중심으로 표시됩니다.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            {[{ v: 2, label: "GA / 대리점" }, { v: 1, label: "전속(원수사)" }].map((o) => (
              <button
                key={o.v}
                disabled={saving}
                onClick={() => patch({ affiliation_type: o.v }, "위촉 형태를 저장했어요")}
                className={`rounded-xl border px-4 py-3 text-[14px] font-bold transition ${
                  p.affiliation_type === o.v
                    ? "border-brand bg-brand-soft text-brand"
                    : "border-line text-ink2 hover:bg-surface2"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </Card>

        {/* 내 소개 카드 한줄소개 */}
        <Card className="px-5 py-4">
          <div className="text-[15px] font-bold text-ink">내 소개 카드 한줄소개</div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            판촉물의 '내 소개 카드'에 보이는 한 줄이에요. 예: 3년차 손해보험 전문, 맞춤설계로 도와드려요.
          </p>
          <input
            value={introText}
            onChange={(e) => setIntroText(e.target.value)}
            maxLength={120}
            placeholder="한 줄 소개를 적어보세요"
            className="mt-3 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
          />
          <button
            disabled={saving}
            onClick={() => patch({ intro_text: introText.trim() }, "소개 문구를 저장했어요")}
            className="mt-2 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2 disabled:opacity-60"
          >
            저장
          </button>
        </Card>

        {/* 관리직 KPI 공유 */}
        <Card className="px-5 py-4">
          <div className="text-[15px] font-bold text-ink">관리자에게 공유</div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            관리자(지점장·팀장)에게 내 <b>집계 수치</b>만 공유해요(개별 고객 이름·정보는 공유 안 함). 어디까지 보여줄지 고르세요.
          </p>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {([
              { v: "none", label: "공유 안 함", desc: "보이지 않음" },
              { v: "activity", label: "활동만", desc: "고객수·신규·미팅·단계" },
              { v: "full", label: "활동+실적", desc: "보험료·유지율까지" },
            ] as const).map((o) => (
              <button
                key={o.v}
                disabled={saving}
                onClick={() => patch({ manager_share_level: o.v }, "공유 설정을 저장했어요")}
                aria-pressed={p.manager_share_level === o.v}
                className={`rounded-xl border px-2 py-2.5 text-center transition ${
                  p.manager_share_level === o.v
                    ? "border-brand bg-accent-tint text-brand"
                    : "border-line bg-surface2 text-ink3 hover:bg-surface"
                }`}
              >
                <div className="text-[13px] font-bold">{o.label}</div>
                <div className="text-[10px] mt-0.5 leading-tight">{o.desc}</div>
              </button>
            ))}
          </div>
          <label className="mt-3 block">
            <span className="text-[12px] text-ink3">관리직 이메일</span>
            <div className="mt-1 flex gap-2">
              <input
                type="email"
                value={managerEmail}
                onChange={(e) => setManagerEmail(e.target.value)}
                placeholder="manager@example.com"
                className="flex-1 rounded-xl border border-line px-3 py-2 text-[14px]"
              />
              <button
                disabled={saving}
                onClick={() => patch({ manager_email: managerEmail.trim() }, "관리직을 연결했어요")}
                className="rounded-xl bg-brand text-white text-[13px] font-bold px-4 disabled:opacity-60"
              >
                연결
              </button>
            </div>
          </label>
        </Card>

        {/* 익명 코호트 동의 */}
        <Card className="px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="text-[15px] font-bold text-ink">익명 코호트 분석 참여</div>
            <button
              disabled={saving}
              onClick={() => patch({ cohort_opt_in: !p.cohort_opt_in }, "코호트 설정을 저장했어요")}
              className={`relative w-11 h-6 rounded-full transition ${p.cohort_opt_in ? "bg-brand" : "bg-line"}`}
              aria-pressed={p.cohort_opt_in}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${p.cohort_opt_in ? "left-[22px]" : "left-0.5"}`} />
            </button>
          </div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            익명·집계 형태로만 보장 분포 통계에 기여합니다(개인 식별 정보 제외). 끄면 참여하지 않아요.
          </p>
        </Card>

        {/* 미팅 예약 설정 — 일정 탭으로 이동함 */}
        <Card className="px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="text-[15px] font-bold text-ink">미팅 예약 설정</div>
            <Link href="/schedule" className="text-[13px] font-semibold text-brand">일정 탭으로 →</Link>
          </div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            예약 안내 메시지·장소·가능 시간 설정은 <b>일정 탭</b>으로 옮겼어요.
          </p>
        </Card>

        {/* 소셜 계정 연동 — 항상 노출(구글 연동/준비중 + 카카오·네이버 추후 예정) */}
        <Card className="px-5 py-4">
          <div className="text-[15px] font-bold text-ink">소셜 계정 연동</div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            구글 계정을 연동하면 <b>구글 로그인</b>과 <b>구글 캘린더(미팅 자동 기록)</b>를 함께 쓸 수 있어요.
          </p>

          {/* 구글 */}
          <div className="mt-3 flex items-center justify-between gap-3 py-2.5 border-t border-line">
            <div className="flex items-center gap-2.5 min-w-0">
              <span className="w-8 h-8 rounded-lg bg-surface2 flex items-center justify-center text-[15px] font-bold text-ink shrink-0">G</span>
              <div className="min-w-0">
                <div className="text-[14px] font-semibold text-ink">구글</div>
                <div className="text-[12px] text-ink3 truncate">
                  {GOOGLE_CLIENT_ID
                    ? (p.google_calendar_connected ? "연동됨 · 캘린더 동기화 중" : "로그인 + 캘린더 연동")
                    : "준비 중 (관리자 설정 후 사용 가능)"}
                </div>
              </div>
            </div>
            {GOOGLE_CLIENT_ID ? (
              p.google_calendar_connected ? (
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[13px] font-bold text-enough">✓ 연동됨</span>
                  <button disabled={saving} onClick={disconnectGcal} className="text-[12px] text-ink3 underline disabled:opacity-60">해제</button>
                </div>
              ) : (
                <button onClick={connectGoogleCalendar} className="rounded-lg bg-brand text-white text-[13px] font-bold px-3 py-1.5 shrink-0">연동하기</button>
              )
            ) : (
              <span className="text-[12px] text-ink3 bg-surface2 rounded-full px-2.5 py-1 shrink-0">준비 중</span>
            )}
          </div>

          {/* 구글 캘린더 고객 이름 마스킹 (연동된 경우만) */}
          {GOOGLE_CLIENT_ID && p.google_calendar_connected && (
            <label className="flex items-center justify-between gap-3 py-2 pl-[42px]">
              <span className="text-[12px] text-ink2">캘린더에 고객 이름 가리기(예: 김○○)</span>
              <button
                disabled={saving}
                onClick={() => patch({ google_calendar_mask_name: !p.google_calendar_mask_name }, "저장했어요")}
                className={`relative w-11 h-6 rounded-full transition shrink-0 ${p.google_calendar_mask_name ? "bg-brand" : "bg-line"}`}
                aria-pressed={p.google_calendar_mask_name}
              >
                <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${p.google_calendar_mask_name ? "left-[22px]" : "left-0.5"}`} />
              </button>
            </label>
          )}

          {/* 카카오 · 네이버 — 추후 도입 예정 */}
          {[
            { label: "카카오", mark: "K", color: "bg-[#FEE500] text-[#3C1E1E]" },
            { label: "네이버", mark: "N", color: "bg-[#03C75A] text-white" },
          ].map((s) => (
            <div key={s.label} className="flex items-center justify-between gap-3 py-2.5 border-t border-line">
              <div className="flex items-center gap-2.5">
                <span className={`w-8 h-8 rounded-lg flex items-center justify-center text-[15px] font-bold ${s.color}`}>{s.mark}</span>
                <div>
                  <div className="text-[14px] font-semibold text-ink2">{s.label}</div>
                  <div className="text-[12px] text-ink3">추후 도입 예정</div>
                </div>
              </div>
              <span className="text-[12px] text-ink3 bg-surface2 rounded-full px-2.5 py-1">예정</span>
            </div>
          ))}

          <p className="mt-3 text-[12px] text-ink3 leading-5">
            구글 캘린더 연동 시 미팅 확정 시점에 <b>고객 이름·시간·방식</b>만 Google(미국 서버) 캘린더에 기록돼요. 병력·보험 정보는 전송되지 않습니다.
          </p>
        </Card>

        {/* 비밀번호 변경 + 회원 탈퇴 */}
        {p && <AccountSecurity hasPassword={p.has_usable_password} email={p.email} />}

        {/* 로그아웃 */}
        <Card className="px-5 py-4">
          <button
            onClick={async () => {
              try { await logout(); } catch { /* 토큰 만료 등은 무시하고 로그아웃 진행 */ }
              router.push("/login");
            }}
            className="w-full rounded-xl border border-line text-[14px] font-semibold text-ink2 py-3 hover:bg-surface2 transition"
          >
            로그아웃
          </button>
        </Card>
        </div>
      </main>
    </div>
  );
}
