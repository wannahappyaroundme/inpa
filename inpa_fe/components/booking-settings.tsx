"use client";

// 예약 설정 — 내 이름·안내 메시지·대면 장소·기본 시간. (마이페이지에서 일정 탭으로 이동)
// updateProfile(PATCH /auth/profile/) 로 저장. BE 변경 없음(Profile 필드 그대로 재사용).

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Card } from "@/components/ui";
import { getProfile, updateProfile } from "@/lib/api";

export function BookingSettings() {
  const [name, setName] = useState("");
  const [tpl, setTpl] = useState("");
  const [loc, setLoc] = useState("");
  const [dur, setDur] = useState(30);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    getProfile().then((p) => {
      setName(p.name ?? "");
      setTpl(p.booking_msg_template ?? "");
      setLoc(p.booking_location ?? "");
      setDur(p.booking_default_duration ?? 30);
    }).catch(() => { /* useAuthGuard 처리 */ });
  }, []);

  const save = useCallback(async () => {
    setSaving(true); setMsg(null);
    try {
      await updateProfile({
        name: name.trim(), booking_msg_template: tpl,
        booking_location: loc.trim(), booking_default_duration: dur,
      });
      setMsg("예약 설정을 저장했어요");
      setTimeout(() => setMsg(null), 2000);
    } catch {
      setMsg("저장에 실패했어요");
    } finally { setSaving(false); }
  }, [name, tpl, loc, dur]);

  return (
    <Card className="px-5 py-4">
      <div className="flex items-center justify-between">
        <div className="text-[15px] font-bold text-ink">예약 설정</div>
        <Link href="/settings/meetings" className="text-[13px] font-semibold text-brand">가능한 시간 관리 →</Link>
      </div>
      <p className="mt-1 text-[12px] text-ink3 leading-5">
        고객에게 보낼 예약 링크의 안내 메시지·장소를 설정해요. 메시지에{" "}
        <b>{"{고객명}"} · {"{설계사명}"} · {"{링크}"}</b>를 넣으면 자동으로 채워집니다.
      </p>
      {msg && <div className="mt-2 rounded-lg bg-accent-tint text-brand text-[13px] px-3 py-2">{msg}</div>}
      <label className="mt-3 block">
        <span className="text-[12px] text-ink3">내 이름(메시지의 {"{설계사명}"}에 들어가요)</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="예) 홍길동"
          className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]" />
      </label>
      <label className="mt-3 block">
        <span className="text-[12px] text-ink3">예약 안내 메시지(빈 칸이면 기본 문구)</span>
        <textarea value={tpl} onChange={(e) => setTpl(e.target.value)} rows={4}
          placeholder="안녕하세요 {고객명}님, {설계사명}입니다. 아래 링크에서 편하신 시간을 골라주세요. {링크}"
          className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[13px] leading-5" />
      </label>
      <label className="mt-3 block">
        <span className="text-[12px] text-ink3">대면 기본 장소</span>
        <input value={loc} onChange={(e) => setLoc(e.target.value)} placeholder="예) 강남역 스타벅스"
          className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-[14px]" />
      </label>
      <label className="mt-3 block">
        <span className="text-[12px] text-ink3">기본 미팅 시간(분)</span>
        <input type="number" min={10} max={240} value={dur} onChange={(e) => setDur(Number(e.target.value) || 30)}
          className="mt-1 w-28 rounded-xl border border-line px-3 py-2 text-[14px] tnum" />
      </label>
      <button disabled={saving} onClick={save}
        className="mt-3 rounded-xl bg-brand text-white text-[13px] font-bold px-4 py-2.5 disabled:opacity-60">
        예약 설정 저장
      </button>
    </Card>
  );
}
