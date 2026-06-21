"use client";

// 계정·모드 설정 — 위촉 형태(전속/GA), 지점장 KPI 공유, 익명 코호트 동의.
// updateProfile(PATCH /auth/profile/) 로 저장. 동의는 모두 기본 거부(opt-in).

import { useState, useEffect } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { getProfile, updateProfile, getGoogleCalendarConnectUrl, disconnectGoogleCalendar, type ProfileResponse } from "@/lib/api";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

export default function AccountSettingsPage() {
  const ready = useAuthGuard();
  const [p, setP] = useState<ProfileResponse | null>(null);
  const [managerEmail, setManagerEmail] = useState("");
  const [name, setName] = useState("");
  const [bookingTpl, setBookingTpl] = useState("");
  const [bookingLoc, setBookingLoc] = useState("");
  const [bookingDur, setBookingDur] = useState(30);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    getProfile().then((res) => {
      setP(res);
      setManagerEmail(res.manager_email ?? "");
      setName(res.name ?? "");
      setBookingTpl(res.booking_msg_template ?? "");
      setBookingLoc(res.booking_location ?? "");
      setBookingDur(res.booking_default_duration ?? 30);
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
      <main className="mx-auto max-w-xl px-4 sm:px-6 py-6 space-y-4">
        <h1 className="text-[22px] font-extrabold text-ink">계정 · 모드 설정</h1>
        {msg && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-[13px] text-emerald-700">{msg}</div>
        )}

        {/* 위촉 형태 */}
        <Card className="px-5 py-4">
          <div className="text-[15px] font-bold text-ink">위촉 형태</div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            전속(원수사)은 다사 갈아타기 비교 대신 <b>자사 보장공백</b> 중심으로 표시됩니다.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            {[{ v: 2, label: "GA / 대리점" }, { v: 1, label: "전속(원수사)" }].map((o) => (
              <button
                key={o.v}
                disabled={saving}
                onClick={() => patch({ affiliation_type: o.v }, "위촉 형태를 저장했어요")}
                className={`rounded-xl border px-4 py-3 text-[14px] font-bold transition ${
                  p.affiliation_type === o.v
                    ? "border-brand bg-accent-tint text-brand"
                    : "border-line text-ink2 hover:bg-surface2"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </Card>

        {/* 지점장 KPI 공유 */}
        <Card className="px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="text-[15px] font-bold text-ink">지점장에게 KPI 공유</div>
            <button
              disabled={saving}
              onClick={() => patch({ manager_share_opt_in: !p.manager_share_opt_in }, "공유 설정을 저장했어요")}
              className={`relative w-11 h-6 rounded-full transition ${p.manager_share_opt_in ? "bg-brand" : "bg-line"}`}
              aria-pressed={p.manager_share_opt_in}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${p.manager_share_opt_in ? "left-[22px]" : "left-0.5"}`} />
            </button>
          </div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            켜면 지점장이 내 <b>집계 KPI</b>(고객수·환수위험·공유열람)만 봅니다. 개별 고객 정보는 공유되지 않아요.
          </p>
          <label className="mt-3 block">
            <span className="text-[12px] text-ink3">지점장 이메일</span>
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
                onClick={() => patch({ manager_email: managerEmail.trim() }, "지점장을 연결했어요")}
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

        {/* 미팅 예약 설정 */}
        <Card className="px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="text-[15px] font-bold text-ink">미팅 예약</div>
            <Link href="/settings/meetings" className="text-[13px] font-semibold text-brand">가능한 시간 관리 →</Link>
          </div>
          <p className="mt-1 text-[12px] text-ink3 leading-5">
            고객에게 보낼 예약 링크의 안내 메시지·장소를 설정해요. 메시지에{" "}
            <b>{"{고객명}"} · {"{설계사명}"} · {"{링크}"}</b>를 넣으면 자동으로 채워집니다.
          </p>
          <label className="mt-3 block">
            <span className="text-[12px] text-ink3">내 이름(메시지의 {"{설계사명}"}에 들어가요)</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예) 홍길동"
              className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]"
            />
          </label>
          <label className="mt-3 block">
            <span className="text-[12px] text-ink3">예약 안내 메시지(빈 칸이면 기본 문구)</span>
            <textarea
              value={bookingTpl}
              onChange={(e) => setBookingTpl(e.target.value)}
              rows={4}
              placeholder="안녕하세요 {고객명}님, {설계사명}입니다. 아래 링크에서 편하신 시간을 골라주세요. {링크}"
              className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[13px] leading-5"
            />
          </label>
          <label className="mt-3 block">
            <span className="text-[12px] text-ink3">대면 기본 장소</span>
            <input
              value={bookingLoc}
              onChange={(e) => setBookingLoc(e.target.value)}
              placeholder="예) 강남역 스타벅스"
              className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]"
            />
          </label>
          <label className="mt-3 block">
            <span className="text-[12px] text-ink3">기본 미팅 시간(분)</span>
            <input
              type="number" min={10} max={240}
              value={bookingDur}
              onChange={(e) => setBookingDur(Number(e.target.value) || 30)}
              className="mt-1 w-28 rounded-xl border border-line px-3 py-2 text-[14px] tnum"
            />
          </label>
          <button
            disabled={saving}
            onClick={() => patch(
              { name: name.trim(), booking_msg_template: bookingTpl, booking_location: bookingLoc.trim(), booking_default_duration: bookingDur },
              "예약 설정을 저장했어요"
            )}
            className="mt-3 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5 disabled:opacity-60"
          >
            예약 설정 저장
          </button>
        </Card>

        {/* 구글 캘린더 연동 — 클라이언트 ID 설정 시에만 노출 */}
        {GOOGLE_CLIENT_ID && (
          <Card className="px-5 py-4">
            <div className="flex items-center justify-between">
              <div className="text-[15px] font-bold text-ink">구글 캘린더 연동</div>
              {p.google_calendar_connected ? (
                <button disabled={saving} onClick={disconnectGcal} className="text-[13px] font-semibold text-danger disabled:opacity-60">
                  연동 해제
                </button>
              ) : (
                <button onClick={connectGoogleCalendar} className="text-[13px] font-bold text-brand">
                  연동하기
                </button>
              )}
            </div>
            <p className="mt-1 text-[12px] text-ink3 leading-5">
              연동하면 미팅 확정 시 <b>고객 이름·시간·방식</b>이 Google(미국 서버) 캘린더에 기록돼요.
              병력·보험 정보는 전송되지 않습니다.
            </p>
            {p.google_calendar_connected && (
              <label className="mt-3 flex items-center justify-between gap-3">
                <span className="text-[13px] text-ink2">캘린더에 고객 이름 가리기(예: 김○○)</span>
                <button
                  disabled={saving}
                  onClick={() => patch({ google_calendar_mask_name: !p.google_calendar_mask_name }, "저장했어요")}
                  className={`relative w-11 h-6 rounded-full transition ${p.google_calendar_mask_name ? "bg-brand" : "bg-line"}`}
                  aria-pressed={p.google_calendar_mask_name}
                >
                  <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${p.google_calendar_mask_name ? "left-[22px]" : "left-0.5"}`} />
                </button>
              </label>
            )}
          </Card>
        )}
      </main>
    </div>
  );
}
