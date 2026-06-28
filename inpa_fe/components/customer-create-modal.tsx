"use client";

// 고객 등록 모달 — 이름만 필수, 나머지 선택. createCustomer 실 API 연결.
// booking-modal.tsx 와 동일한 시트형 모달 패턴.

import { useState, useCallback, useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react";
import {
  createCustomer, createConsentLog, searchJobs, LEAD_SOURCES, ApiError,
  type CustomerDetail, type JobMatch,
} from "@/lib/api";
import { AVATAR_PALETTE, CustomerAvatar } from "@/components/ui";

// 직업급수 칩 색 — 1급(저위험)=초록 … 3급(고위험)=빨강, 기타=회색
function gradeChip(grade: number): string {
  if (grade === 1) return "bg-emerald-100 text-emerald-700";
  if (grade === 2) return "bg-amber-100 text-amber-700";
  if (grade === 3) return "bg-rose-100 text-rose-700";
  return "bg-surface2 text-ink3";
}

export function CustomerCreateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (c: CustomerDetail) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [gender, setGender] = useState<"" | "1" | "2">("");
  const [birth, setBirth] = useState("");
  const [memo, setMemo] = useState("");
  const [color, setColor] = useState("");
  const [avatarLabel, setAvatarLabel] = useState("");
  const [leadSource, setLeadSource] = useState("");
  const [piConsent, setPiConsent] = useState(false);
  const [mkConsent, setMkConsent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 직업급수 찾기
  const [jobQuery, setJobQuery] = useState("");
  const [jobResults, setJobResults] = useState<JobMatch[]>([]);
  const [jobOpen, setJobOpen] = useState(false);
  const [jobSearching, setJobSearching] = useState(false);
  const [selectedJob, setSelectedJob] = useState<JobMatch | null>(null);

  // 바텀시트 드래그(아래로 내려 닫기)
  const [dragY, setDragY] = useState(0);
  const [dragging, setDragging] = useState(false);
  const startYRef = useRef<number | null>(null);
  const dragYRef = useRef(0);

  // 직업급수 검색 — 250ms 디바운스. 빈 질의는 결과 비움.
  useEffect(() => {
    const q = jobQuery.trim();
    if (!q) { setJobResults([]); setJobOpen(false); return; }
    let alive = true;
    setJobSearching(true);
    const t = setTimeout(() => {
      searchJobs(q)
        .then((rows) => { if (alive) { setJobResults(rows); setJobOpen(true); } })
        .catch(() => { if (alive) setJobResults([]); })
        .finally(() => { if (alive) setJobSearching(false); });
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [jobQuery]);

  const pickJob = useCallback((j: JobMatch) => {
    setSelectedJob(j);
    setJobQuery("");
    setJobResults([]);
    setJobOpen(false);
  }, []);

  // 드래그: 핸들에서만(터치=touch-none). 120px 이상 내리면 닫기, 아니면 복귀.
  const onDragDown = useCallback((e: ReactPointerEvent) => {
    startYRef.current = e.clientY;
    setDragging(true);
    try { (e.target as HTMLElement).setPointerCapture(e.pointerId); } catch { /* noop */ }
  }, []);
  const onDragMove = useCallback((e: ReactPointerEvent) => {
    if (startYRef.current === null) return;
    const dy = Math.max(0, e.clientY - startYRef.current);
    dragYRef.current = dy;
    setDragY(dy);
  }, []);
  const onDragUp = useCallback(() => {
    if (startYRef.current === null) return;
    const dy = dragYRef.current;
    startYRef.current = null;
    setDragging(false);
    if (dy > 120) {
      onClose();
    } else {
      dragYRef.current = 0;
      setDragY(0);
    }
  }, [onClose]);

  const submit = useCallback(async () => {
    if (!name.trim()) {
      setError("이름을 입력해 주세요.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const c = await createCustomer({
        name: name.trim(),
        gender: gender || undefined,
        birth_day: birth || undefined,
        mobile_phone_number: phone.trim() || undefined,
        memo: memo.trim() || undefined,
        color: color || undefined,
        avatar_label: avatarLabel.trim() || undefined,
        lead_source: leadSource || undefined,
        job_code: selectedJob ? String(selectedJob.id) : undefined,
      });
      // 설계사 기록(planner_attested) — 체크된 동의를 감사 로그로 남김(법적 강건성은 본인 링크).
      const scopes: string[] = [];
      if (piConsent) scopes.push("personal_info");
      if (mkConsent) scopes.push("marketing");
      await Promise.allSettled(scopes.map((scope) => createConsentLog(c.id, { scope })));
      onCreated(c);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "등록 중 오류가 발생했어요. 다시 시도해 주세요."
      );
    } finally {
      setSaving(false);
    }
  }, [name, gender, birth, phone, memo, color, avatarLabel, leadSource, selectedJob, piConsent, mkConsent, onCreated]);

  const inputCls =
    "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand transition";

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="customer-create-title"
    >
      <div
        className="w-full sm:max-w-md max-h-[92dvh] overflow-y-auto bg-surface rounded-t-3xl sm:rounded-2xl px-6 pt-3 pb-8 shadow-xl"
        style={{
          transform: dragY ? `translateY(${dragY}px)` : undefined,
          transition: dragging ? "none" : "transform 0.25s ease",
        }}
      >
        {/* 드래그 핸들 — 아래로 슬라이드하면 닫기(모바일 바텀시트). 데스크탑에선 장식 */}
        <div
          onPointerDown={onDragDown}
          onPointerMove={onDragMove}
          onPointerUp={onDragUp}
          onPointerCancel={onDragUp}
          className="flex justify-center pt-1 pb-3 cursor-grab active:cursor-grabbing touch-none"
          aria-hidden
        >
          <span className="h-1.5 w-10 rounded-full bg-line" />
        </div>
        <h2 id="customer-create-title" className="text-[18px] font-extrabold text-ink">
          고객 등록
        </h2>
        <p className="mt-2 text-[13px] text-ink3 leading-5">
          이름만 입력해도 등록돼요. 나머지는 나중에 채워도 됩니다.
        </p>

        {error && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
            {error}
          </div>
        )}

        <div className="mt-5 flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">이름 *</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예) 김보장"
              autoFocus
              className={inputCls}
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">연락처</span>
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="010-1234-5678"
              inputMode="tel"
              className={inputCls}
            />
          </label>

          <div className="flex gap-3">
            <div className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink3">성별</span>
              <div className="flex gap-1.5">
                {([["1", "남"], ["2", "여"]] as const).map(([v, label]) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setGender((g) => (g === v ? "" : v))}
                    className={`w-12 rounded-xl border py-2.5 text-[14px] font-semibold transition ${
                      gender === v
                        ? "border-brand bg-accent-tint text-brand"
                        : "border-line text-ink3"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <label className="flex flex-col gap-1 flex-1">
              <span className="text-[12px] font-semibold text-ink3">생년월일</span>
              <input
                type="date"
                value={birth}
                onChange={(e) => setBirth(e.target.value)}
                className={inputCls}
              />
            </label>
          </div>

          {/* 직업급수 찾기 — 검색 → 선택 시 job_code 적용(미선택 가능) */}
          <div className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">직업급수 (선택 — 검색해서 적용)</span>
            {selectedJob ? (
              <div className="flex items-center justify-between gap-2 rounded-xl border border-line bg-accent-tint px-3.5 py-2.5">
                <div className="min-w-0">
                  <div className="text-[14px] font-semibold text-ink truncate">{selectedJob.name}</div>
                  {selectedJob.description_short && (
                    <div className="text-[11px] text-ink3 truncate">{selectedJob.description_short}</div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className={`rounded-full text-[12px] font-bold px-2 py-0.5 ${gradeChip(selectedJob.risk_grade)}`}>
                    {selectedJob.risk_grade_label}
                  </span>
                  <button
                    type="button"
                    onClick={() => setSelectedJob(null)}
                    className="text-[12px] text-ink3 hover:text-ink underline"
                  >
                    변경
                  </button>
                </div>
              </div>
            ) : (
              <div className="relative">
                <input
                  value={jobQuery}
                  onChange={(e) => setJobQuery(e.target.value)}
                  onFocus={() => { if (jobResults.length) setJobOpen(true); }}
                  placeholder="직업명·키워드 (예: 의사, 시의원, 용접)"
                  className={inputCls}
                />
                {jobOpen && jobQuery.trim() && (
                  <div className="absolute z-10 mt-1 w-full max-h-56 overflow-y-auto rounded-xl border border-line bg-surface shadow-lg">
                    {jobSearching && jobResults.length === 0 ? (
                      <div className="px-3.5 py-2.5 text-[13px] text-ink3">찾는 중…</div>
                    ) : jobResults.length > 0 ? (
                      jobResults.map((j) => (
                        <button
                          key={j.id}
                          type="button"
                          onClick={() => pickJob(j)}
                          className="flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left hover:bg-surface2 border-b border-line last:border-b-0"
                        >
                          <span className="min-w-0">
                            <span className="block text-[14px] text-ink truncate">{j.name}</span>
                            {j.description_short && (
                              <span className="block text-[11px] text-ink3 truncate">{j.description_short}</span>
                            )}
                          </span>
                          <span className={`shrink-0 rounded-full text-[12px] font-bold px-2 py-0.5 ${gradeChip(j.risk_grade)}`}>
                            {j.risk_grade_label}
                          </span>
                        </button>
                      ))
                    ) : (
                      <div className="px-3.5 py-2.5 text-[13px] text-ink3">검색 결과가 없어요.</div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">메모</span>
            <textarea
              value={memo}
              onChange={(e) => setMemo(e.target.value)}
              rows={2}
              placeholder="상담 내용·특이사항 (선택)"
              className={inputCls}
            />
          </label>

          {/* 유입 경로 — 측정용(소개/명함/행사/직접). 셀프진단은 자동 태깅 */}
          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-ink3">유입 경로 (선택)</span>
            <select
              value={leadSource}
              onChange={(e) => setLeadSource(e.target.value)}
              className={`${inputCls} bg-surface`}
            >
              <option value="">선택 안 함</option>
              {LEAD_SOURCES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </label>

          {/* 동의(설계사 기록) — 분리 체크. 본인 동의 링크는 등록 후 고객상세에서. */}
          <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface px-3.5 py-3">
            <span className="text-[12px] font-semibold text-ink3">동의 받음 기록 (선택)</span>
            <label className="flex items-start gap-2 cursor-pointer">
              <input type="checkbox" checked={piConsent} onChange={(e) => setPiConsent(e.target.checked)} className="mt-0.5" />
              <span className="text-[12px] text-ink2 leading-4">개인정보 수집·이용 동의를 받았어요</span>
            </label>
            <label className="flex items-start gap-2 cursor-pointer">
              <input type="checkbox" checked={mkConsent} onChange={(e) => setMkConsent(e.target.checked)} className="mt-0.5" />
              <span className="text-[12px] text-ink2 leading-4">마케팅 수신 동의를 받았어요</span>
            </label>
            <p className="text-[11px] text-ink3 leading-4">
              여기 체크는 <b>설계사 기록(메모)</b>이에요. 법적으로 가장 안전한 건 고객 본인이 링크로 직접 동의하는 것 — 등록 후 '동의 요청 링크 복사'를 쓰세요.
            </p>
          </div>

          {/* 아바타 글씨·색상 — 글씨 비우면 인파 로고. 색은 로고/글씨 공통 배경 */}
          <div className="flex flex-col gap-2">
            <span className="text-[12px] font-semibold text-ink3">아바타 글씨·색상 (선택 — 분류용)</span>
            <div className="flex items-center gap-3">
              <CustomerAvatar label={avatarLabel} color={color || null} size={40} />
              <input
                value={avatarLabel}
                onChange={(e) => setAvatarLabel(e.target.value.slice(0, 3))}
                placeholder="약자·숫자 (비우면 로고)"
                maxLength={3}
                className="flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
              />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[11px] text-ink3 mr-0.5">배경</span>
              <button
                type="button"
                onClick={() => setColor("")}
                className={`h-7 px-2 rounded-full border text-[10px] font-semibold ${color === "" ? "border-brand text-brand" : "border-line text-ink3"}`}
                title="기본 배경"
              >
                기본
              </button>
              {AVATAR_PALETTE.map((hex) => (
                <button
                  key={hex}
                  type="button"
                  onClick={() => setColor(hex)}
                  aria-label={`배경 ${hex}`}
                  className={`w-7 h-7 rounded-full border-2 ${color === hex ? "border-brand" : "border-transparent"}`}
                  style={{ backgroundColor: hex }}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="mt-6 flex flex-col gap-2.5">
          <button
            onClick={submit}
            disabled={saving}
            className="w-full rounded-2xl bg-brand text-white text-[15px] font-bold py-3.5 disabled:opacity-60 transition"
          >
            {saving ? "등록 중…" : "등록하기"}
          </button>
          <button
            onClick={onClose}
            disabled={saving}
            className="w-full rounded-2xl border border-line bg-surface text-[14px] font-semibold text-ink2 py-3 disabled:opacity-60 transition"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
