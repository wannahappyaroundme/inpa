"use client";

import { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  listReminderRules,
  updateReminderRules,
  type ReminderRule,
  type NotifType,
} from "@/lib/api";

// ─── 알림 유형 메타 (표시 순서 고정) ─────────────────────────────────────────
const RULE_META: {
  rule_type: NotifType;
  label: string;
  description: string;
  fixedDays: boolean;
}[] = [
  {
    rule_type: "expiry_soon",
    label: "만기 임박",
    description: "고객 보험 만기일 전 알림",
    fixedDays: false,
  },
  {
    rule_type: "birthday_soon",
    label: "고객 생일",
    description: "고객 생일 전 알림",
    fixedDays: false,
  },
  {
    rule_type: "consult_reminder",
    label: "상담 약속",
    description: "상담 약속일 전 알림",
    fixedDays: false,
  },
  {
    rule_type: "task_due",
    label: "할 일 마감",
    description: "할 일 마감일 전 알림",
    fixedDays: false,
  },
  {
    rule_type: "share_unread",
    label: "공유 미열람 (24시간)",
    description: "공유 링크를 24시간 내 열람하지 않은 경우 알림",
    fixedDays: true, // days_before 변경 불가 (항상 24h 고정)
  },
];

// ─── 기본값 — BE에서 아직 생성 안 됐을 때 대체값 ──────────────────────────────
const DEFAULT_DAYS: Record<NotifType, number> = {
  expiry_soon: 30,
  birthday_soon: 7,
  consult_reminder: 1,
  task_due: 1,
  share_unread: 0,
  unpaid_d_alert: 0,        // 스케줄 대상 아님(환수는 on-demand). 자리값.
  self_diagnosis_lead: 0,   // 즉시 이벤트. 자리값.
  board_comment: 0,
  board_like: 0,
  meeting_booked: 0,        // 즉시 이벤트(예약 요청). 스케줄 대상 아님 — 자리값.
};

type LocalRule = {
  rule_type: NotifType;
  days_before: number;
  enabled: boolean;
  email_enabled: boolean;
};

function buildLocalRules(serverRules: ReminderRule[]): Record<NotifType, LocalRule> {
  const map: Record<string, LocalRule> = {};
  for (const r of serverRules) {
    map[r.rule_type] = {
      rule_type: r.rule_type,
      days_before: r.days_before,
      enabled: r.enabled,
      email_enabled: r.email_enabled,
    };
  }
  // 누락된 rule_type은 기본값으로 채움
  for (const m of RULE_META) {
    if (!map[m.rule_type]) {
      map[m.rule_type] = {
        rule_type: m.rule_type,
        days_before: DEFAULT_DAYS[m.rule_type],
        enabled: true,
        email_enabled: false,
      };
    }
  }
  return map as Record<NotifType, LocalRule>;
}

// ─── 리마인더 설정 본체 ───────────────────────────────────────────────────────
function RemindersContent() {
  const ready = useAuthGuard();

  const [rules, setRules] = useState<Record<NotifType, LocalRule> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    listReminderRules()
      .then((data) => setRules(buildLocalRules(data)))
      .catch(() => setLoadError("알림 설정을 불러오지 못했어요. 잠시 후 다시 시도하세요."));
  }, [ready]);

  if (!ready) return null;

  const updateRule = (
    rule_type: NotifType,
    patch: Partial<Omit<LocalRule, "rule_type">>
  ) => {
    setSavedOk(false);
    setSaveError(null);
    setRules((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        [rule_type]: { ...prev[rule_type], ...patch },
      };
    });
  };

  const handleSave = async () => {
    if (!rules) return;
    setSaving(true);
    setSaveError(null);
    setSavedOk(false);
    try {
      const payload = RULE_META.map((m) => ({
        rule_type: rules[m.rule_type].rule_type,
        days_before: rules[m.rule_type].days_before,
        enabled: rules[m.rule_type].enabled,
        email_enabled: rules[m.rule_type].email_enabled,
      }));
      await updateReminderRules(payload);
      setSavedOk(true);
    } catch {
      setSaveError("저장에 실패했어요. 잠시 후 다시 시도하세요.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-dvh">
      <AppNav />
      <main className="mx-auto max-w-lg px-4 sm:px-6 py-6">
        {/* 헤더 */}
        <div className="flex items-center gap-3 mb-5">
          <Link href="/notifications" className="text-[13px] text-ink3 hover:text-ink">
            ← 알림
          </Link>
          <h1 className="text-[20px] font-extrabold text-ink">알림 설정</h1>
        </div>

        {/* 로드 에러 */}
        {loadError && (
          <div className="mb-4 p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger">
            {loadError}
          </div>
        )}

        {/* 로딩 스켈레톤 */}
        {!rules && !loadError && (
          <Card className="divide-y divide-line">
            {RULE_META.map((m) => (
              <div key={m.rule_type} className="p-4 animate-pulse space-y-2">
                <div className="h-4 bg-line rounded w-1/3" />
                <div className="h-3 bg-line rounded w-2/3" />
              </div>
            ))}
          </Card>
        )}

        {/* 설정 목록 */}
        {rules && (
          <Card className="divide-y divide-line">
            {RULE_META.map((meta) => {
              const rule = rules[meta.rule_type];
              return (
                <div key={meta.rule_type} className="p-4 space-y-3">
                  {/* 제목 + 켜짐/꺼짐 토글 */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-[15px] font-bold text-ink">{meta.label}</p>
                      <p className="text-[12px] text-ink3 mt-0.5">{meta.description}</p>
                    </div>
                    {/* Toggle switch */}
                    <button
                      role="switch"
                      aria-checked={rule.enabled}
                      aria-label={`${meta.label} 알림 ${rule.enabled ? "켜짐" : "꺼짐"}`}
                      onClick={() => updateRule(meta.rule_type, { enabled: !rule.enabled })}
                      className={`relative inline-flex w-11 h-6 rounded-full transition-colors ${
                        rule.enabled ? "bg-brand" : "bg-line-2"
                      }`}
                    >
                      <span
                        className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                          rule.enabled ? "translate-x-6" : "translate-x-1"
                        }`}
                      />
                    </button>
                  </div>

                  {/* 며칠 전 설정 (켜져 있을 때만 표시) */}
                  {rule.enabled && (
                    <div className="pl-0 space-y-2">
                      {/* days_before — share_unread는 고정 */}
                      {meta.fixedDays ? (
                        <p className="text-[13px] text-ink3">
                          공유 후 24시간이 경과하면 자동 발화됩니다. (변경 불가)
                        </p>
                      ) : (
                        <div className="flex items-center gap-2">
                          <span className="text-[13px] text-ink3">몇 일 전에 알릴까요?</span>
                          <input
                            type="number"
                            min={0}
                            max={90}
                            value={rule.days_before}
                            onChange={(e) => {
                              const v = parseInt(e.target.value, 10);
                              if (!isNaN(v) && v >= 0 && v <= 90) {
                                updateRule(meta.rule_type, { days_before: v });
                              }
                            }}
                            className="w-16 rounded-lg border border-line bg-surface px-2 py-1 text-[14px] text-ink text-center tnum outline-none focus:border-brand"
                          />
                          <span className="text-[13px] text-ink3">일 전</span>
                        </div>
                      )}

                      {/* 이메일 opt-in */}
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={rule.email_enabled}
                          onChange={(e) =>
                            updateRule(meta.rule_type, { email_enabled: e.target.checked })
                          }
                          className="w-4 h-4 rounded accent-brand"
                        />
                        <span className="text-[13px] text-ink3">
                          이메일로도 받기
                          <span className="ml-1 text-[11px] text-muted">(기본 꺼짐)</span>
                        </span>
                      </label>
                    </div>
                  )}
                </div>
              );
            })}
          </Card>
        )}

        {/* 저장 버튼 */}
        {rules && (
          <div className="mt-5 space-y-2">
            {saveError && (
              <p className="text-[13px] text-danger text-center">{saveError}</p>
            )}
            {savedOk && (
              <p className="text-[13px] text-success text-center">저장되었어요.</p>
            )}
            <button
              onClick={handleSave}
              disabled={saving}
              className="w-full rounded-xl bg-brand text-white text-[15px] font-bold py-3 disabled:opacity-50 transition hover:opacity-90"
            >
              {saving ? "저장 중..." : "저장"}
            </button>
          </div>
        )}

        {/* 이메일 opt-in 안내 */}
        {rules && (
          <p className="mt-5 text-[11px] text-muted leading-5 text-center">
            이메일 알림은 가입 이메일로만 발송됩니다. 알림은 설계사 본인에게만
            전송되며, 설계사 본인에게만 표시됩니다.
          </p>
        )}
      </main>
    </div>
  );
}

export default function RemindersPage() {
  return (
    <Suspense>
      <RemindersContent />
    </Suspense>
  );
}
