"use client";

import { useState, useEffect, use } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { Card } from "@/components/ui";
import { useAuthGuard } from "@/lib/useAuthGuard";
import {
  getSample,
  createOrder,
  requestDigitalSample,
  ApiError,
  type PromotionSampleDetail,
  type PromotionFormField,
  type DigitalRequestResult,
} from "@/lib/api";
import { UpgradeModal, type UpgradeModalInfo } from "@/components/upgrade-modal";

// ── 동적 폼 필드 단일 렌더러 ─────────────────────────────────────────────────

interface FieldProps {
  field: PromotionFormField;
  value: unknown;
  onChange: (key: string, val: unknown) => void;
}

function FormField({ field, value, onChange }: FieldProps) {
  const base =
    "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand transition";

  const { key, label, type = "text", required, options } = field;

  switch (type) {
    case "number":
      return (
        <div className="space-y-1.5">
          <label className="block text-[13px] font-semibold text-ink">
            {label}
            {required && <span className="text-danger ml-0.5">*</span>}
          </label>
          <input
            type="number"
            min={field.min as number | undefined}
            step={field.step as number | undefined}
            value={(value as number | "") ?? ""}
            onChange={(e) =>
              onChange(key, e.target.value === "" ? "" : Number(e.target.value))
            }
            className={base}
          />
        </div>
      );

    case "textarea":
      return (
        <div className="space-y-1.5">
          <label className="block text-[13px] font-semibold text-ink">
            {label}
            {required && <span className="text-danger ml-0.5">*</span>}
          </label>
          <textarea
            rows={3}
            maxLength={field.maxLength as number | undefined}
            value={(value as string) ?? ""}
            onChange={(e) => onChange(key, e.target.value)}
            className={`${base} resize-none`}
          />
        </div>
      );

    case "select":
      return (
        <div className="space-y-1.5">
          <label className="block text-[13px] font-semibold text-ink">
            {label}
            {required && <span className="text-danger ml-0.5">*</span>}
          </label>
          <select
            value={(value as string) ?? ""}
            onChange={(e) => onChange(key, e.target.value)}
            className={`${base} appearance-none`}
          >
            <option value="">선택하세요</option>
            {(options ?? []).map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>
      );

    case "radio":
      return (
        <div className="space-y-1.5">
          <p className="text-[13px] font-semibold text-ink">
            {label}
            {required && <span className="text-danger ml-0.5">*</span>}
          </p>
          <div className="flex flex-wrap gap-2">
            {(options ?? []).map((opt) => (
              <label
                key={opt}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-xl border text-[13px] font-medium cursor-pointer transition ${
                  value === opt
                    ? "border-brand bg-accent-tint text-brand"
                    : "border-line bg-surface text-ink hover:bg-surface2"
                }`}
              >
                <input
                  type="radio"
                  name={key}
                  value={opt}
                  checked={value === opt}
                  onChange={() => onChange(key, opt)}
                  className="sr-only"
                />
                {opt}
              </label>
            ))}
          </div>
        </div>
      );

    case "checkbox":
      return (
        <div className="space-y-1.5">
          <p className="text-[13px] font-semibold text-ink">
            {label}
            {required && <span className="text-danger ml-0.5">*</span>}
          </p>
          <div className="flex flex-wrap gap-2">
            {(options ?? []).map((opt) => {
              const checked = Array.isArray(value) && (value as string[]).includes(opt);
              return (
                <label
                  key={opt}
                  className={`flex items-center gap-2 px-3.5 py-2 rounded-xl border text-[13px] font-medium cursor-pointer transition ${
                    checked
                      ? "border-brand bg-accent-tint text-brand"
                      : "border-line bg-surface text-ink hover:bg-surface2"
                  }`}
                >
                  <input
                    type="checkbox"
                    value={opt}
                    checked={checked}
                    onChange={(e) => {
                      const prev = Array.isArray(value) ? (value as string[]) : [];
                      const next = e.target.checked
                        ? [...prev, opt]
                        : prev.filter((v) => v !== opt);
                      onChange(key, next);
                    }}
                    className="sr-only"
                  />
                  {opt}
                </label>
              );
            })}
          </div>
        </div>
      );

    case "file":
      // 스토리지 정책 미확정(G-1) — 파일 선택 UI만, 실제 업로드 안 함
      return (
        <div className="space-y-1.5">
          <label className="block text-[13px] font-semibold text-ink">
            {label}
            {required && <span className="text-danger ml-0.5">*</span>}
          </label>
          <div className="rounded-xl border border-dashed border-line-2 bg-surface2 p-4 text-center">
            <p className="text-[12px] text-ink3">
              파일 첨부는 현재 지원하지 않아요. 이메일로 별도 전송해 주세요.
            </p>
          </div>
        </div>
      );

    default:
      // text, 그 외
      return (
        <div className="space-y-1.5">
          <label className="block text-[13px] font-semibold text-ink">
            {label}
            {required && <span className="text-danger ml-0.5">*</span>}
          </label>
          <input
            type="text"
            maxLength={field.maxLength as number | undefined}
            value={(value as string) ?? ""}
            onChange={(e) => onChange(key, e.target.value)}
            className={base}
          />
        </div>
      );
  }
}

// ── 메인 페이지 ─────────────────────────────────────────────────────────────

export default function SampleDetailPage({
  params,
}: {
  params: Promise<{ sampleId: string }>;
}) {
  const { sampleId } = use(params);
  const router = useRouter();
  const ready = useAuthGuard();

  const [sample, setSample] = useState<PromotionSampleDetail | null>(null);
  const [loadingPage, setLoadingPage] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);

  const [selectedImageIdx, setSelectedImageIdx] = useState(0);
  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const [submitLoading, setSubmitLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [upgradeInfo, setUpgradeInfo] = useState<UpgradeModalInfo | undefined>(undefined);
  // 전자자료(1회 무료 / 어드민 큐) — PM 06.24
  const [digital, setDigital] = useState<DigitalRequestResult | null>(null);
  const [digitalLoading, setDigitalLoading] = useState(false);
  const [digitalError, setDigitalError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    const id = Number(sampleId);
    if (isNaN(id)) {
      setPageError("잘못된 샘플 주소예요.");
      setLoadingPage(false);
      return;
    }
    getSample(id)
      .then((s) => {
        setSample(s);
        // 초기 폼 값 설정
        const init: Record<string, unknown> = {};
        for (const f of s.form_fields) {
          if (f.type === "checkbox") init[f.key] = [];
          else init[f.key] = "";
        }
        setFormValues(init);
      })
      .catch(() => setPageError("샘플 정보를 불러오지 못했어요."))
      .finally(() => setLoadingPage(false));
  }, [ready, sampleId]);

  if (!ready) return null;

  // 필수 필드 모두 채워졌는지 확인
  function isFormValid(): boolean {
    if (!sample) return false;
    for (const f of sample.form_fields) {
      if (!f.required) continue;
      const v = formValues[f.key];
      if (f.type === "file") continue; // 파일은 미지원 — 필수여도 통과(G-1)
      if (f.type === "checkbox") {
        if (!Array.isArray(v) || v.length === 0) return false;
      } else {
        if (v === "" || v === null || v === undefined) return false;
      }
    }
    return true;
  }

  function handleFieldChange(key: string, val: unknown) {
    setFormValues((prev) => ({ ...prev, [key]: val }));
    setSubmitError(null);
    setUpgradeInfo(undefined);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!sample || !isFormValid()) return;
    setSubmitLoading(true);
    setSubmitError(null);
    setUpgradeInfo(undefined);
    try {
      await createOrder({ sample: sample.id, form_response: formValues });
      router.push("/promotion/orders");
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        setUpgradeInfo(err.creditBody ?? { kind: "promotion" });
      } else if (err instanceof ApiError) {
        setSubmitError(err.message || "주문 제출에 실패했어요. 다시 시도해 주세요.");
      } else {
        setSubmitError("주문 제출에 실패했어요. 다시 시도해 주세요.");
      }
    } finally {
      setSubmitLoading(false);
    }
  }

  async function handleDigital() {
    if (!sample) return;
    setDigitalLoading(true);
    setDigitalError(null);
    try {
      const res = await requestDigitalSample(sample.id);
      setDigital(res);
      if (res.mode === "free" && res.file_url) {
        window.open(res.file_url, "_blank", "noopener");
      }
    } catch {
      setDigitalError("요청에 실패했어요. 다시 시도해 주세요.");
    } finally {
      setDigitalLoading(false);
    }
  }

  // ── 로딩 / 에러 ───────────────────────────────────────────────────────────

  if (loadingPage) {
    return (
      <div className="min-h-dvh">
        <AppNav active="promotion" />
        <div className="mt-16 text-center text-[14px] text-ink3">불러오는 중...</div>
      </div>
    );
  }

  if (pageError || !sample) {
    return (
      <div className="min-h-dvh">
        <AppNav active="promotion" />
        <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
          <Link href="/promotion" className="text-[13px] text-brand">← 판촉물 목록</Link>
          <p className="mt-4 text-[14px] text-ink3">{pageError ?? "샘플 정보를 찾을 수 없어요."}</p>
        </main>
      </div>
    );
  }

  const primaryIdx = sample.images.findIndex((img) => img.is_primary);
  const orderedImages =
    sample.images.length > 0
      ? [
          ...sample.images.slice(primaryIdx >= 0 ? primaryIdx : 0, primaryIdx >= 0 ? primaryIdx + 1 : 1),
          ...sample.images.slice(0, primaryIdx >= 0 ? primaryIdx : 0),
          ...sample.images.slice(primaryIdx >= 0 ? primaryIdx + 1 : 1),
        ]
      : [];

  const currentImage = orderedImages[selectedImageIdx];
  const valid = isFormValid();

  return (
    <div className="min-h-dvh">
      <AppNav active="promotion" />

      <UpgradeModal
        open={upgradeInfo !== undefined}
        onClose={() => setUpgradeInfo(undefined)}
        info={upgradeInfo}
      />

      <main className="mx-auto max-w-[1440px] px-4 sm:px-6 py-6">
        {/* 뒤로 가기 */}
        <Link
          href="/promotion"
          className="inline-flex items-center gap-1 text-[13px] text-ink3 hover:text-ink transition mb-5"
        >
          ← 판촉물 목록
        </Link>

        {/* 2열 레이아웃: 모바일=세로, md+=좌우 */}
        <div className="flex flex-col md:flex-row gap-6 md:gap-8">

          {/* ── 왼쪽: 이미지 갤러리 ─────────────────────────────────────── */}
          <div className="w-full md:w-[45%] shrink-0 space-y-3">
            {/* 대표 이미지 */}
            <Card className="overflow-hidden aspect-square">
              {currentImage ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={currentImage.url}
                  alt={sample.name}
                  className="w-full h-full object-contain"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center bg-surface2 text-muted text-[13px]">
                  이미지 없음
                </div>
              )}
            </Card>

            {/* 썸네일 */}
            {orderedImages.length > 1 && (
              <div className="flex gap-2 overflow-x-auto pb-1">
                {orderedImages.map((img, idx) => (
                  <button
                    key={img.id}
                    onClick={() => setSelectedImageIdx(idx)}
                    className={`shrink-0 w-16 h-16 rounded-xl overflow-hidden border-2 transition ${
                      idx === selectedImageIdx
                        ? "border-brand"
                        : "border-transparent hover:border-line-2"
                    }`}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={img.url}
                      alt=""
                      className="w-full h-full object-contain"
                    />
                  </button>
                ))}
              </div>
            )}

            {/* 샘플 설명 */}
            {sample.description && (
              <p className="text-[13px] text-ink3 leading-6 whitespace-pre-wrap">
                {sample.description}
              </p>
            )}
          </div>

          {/* ── 오른쪽: 주문 폼 ─────────────────────────────────────────── */}
          <div className="flex-1 min-w-0">
            {/* 샘플명 / 카테고리 */}
            <div className="mb-5">
              <h1 className="text-[20px] font-extrabold text-ink leading-tight">
                {sample.name}
              </h1>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="text-[12px] font-semibold text-brand bg-accent-tint px-2.5 py-0.5 rounded-full">
                  {sample.category}
                </span>
                {!sample.is_available && (
                  <span className="text-[12px] font-semibold text-muted bg-surface2 px-2.5 py-0.5 rounded-full">
                    주문 불가
                  </span>
                )}
              </div>
            </div>

            {/* 전자자료 — 1회 무료 다운로드 / 2회차+ 어드민 큐 (PM 06.24) */}
            {sample.is_digital && (
              <div className="space-y-4">
                <div className="rounded-xl border border-accent-tint bg-accent-tint/40 p-4">
                  <div className="text-[14px] font-bold text-ink">전자자료, 첫 1회 무료</div>
                  <p className="mt-1 text-[12px] text-ink2 leading-5">
                    처음 1회는 무료로 바로 받을 수 있어요. 그 다음부터는 요청하면 운영팀이 직접 제작해 전달해 드립니다.
                  </p>
                </div>
                {digital && (
                  <div className={`rounded-xl border p-3.5 text-[13px] ${digital.mode === "free" ? "border-line bg-success-tint text-success" : "border-line bg-brand-soft text-brand"}`}>
                    {digital.detail}
                    {digital.mode === "free" && digital.file_url && (
                      <> <a href={digital.file_url} target="_blank" rel="noreferrer" className="font-semibold underline">다운로드 링크 열기</a></>
                    )}
                    {digital.mode === "queued" && (
                      <> 진행 상황은 <Link href="/promotion/orders" className="font-semibold underline">주문 목록</Link>에서 확인하세요.</>
                    )}
                  </div>
                )}
                {digitalError && (
                  <div className="rounded-xl border border-line bg-danger-tint px-4 py-2.5 text-[13px] text-danger">{digitalError}</div>
                )}
                <button
                  onClick={handleDigital}
                  disabled={digitalLoading || !sample.is_available}
                  className="w-full rounded-xl bg-brand text-white text-[15px] font-bold py-3.5 disabled:opacity-40 transition"
                >
                  {digitalLoading ? "처리 중…" : digital ? "다시 요청" : "무료 다운로드 / 요청하기"}
                </button>
                <p className="text-[12px] text-muted leading-5 border-t border-line pt-4">
                  광고심의 적합성은 설계사 본인이 확인해야 합니다. 인파는 내용의 법적 적합성을 보증하지 않습니다.
                </p>
              </div>
            )}

            {/* 동적 폼 (실물 판촉물) */}
            {!sample.is_digital && (
            <form onSubmit={handleSubmit} className="space-y-5">
              {sample.form_fields.map((field) => (
                <FormField
                  key={field.key}
                  field={field}
                  value={formValues[field.key]}
                  onChange={handleFieldChange}
                />
              ))}

              {/* 일반 에러 */}
              {submitError && (
                <div className="p-3 rounded-xl bg-danger-tint border border-line text-[13px] text-danger">
                  {submitError}
                </div>
              )}

              {/* 광고심의 면책 고지 — 항상 노출 (AC-C1) */}
              <p className="text-[12px] text-muted leading-5 border-t border-line pt-4">
                입력한 내용의 광고심의 적합성은 설계사 본인이 확인해야 합니다. 인파는 인쇄 내용의 법적 적합성을 보증하지 않습니다.
              </p>

              {/* 제출 버튼 */}
              <button
                type="submit"
                disabled={!valid || !sample.is_available || submitLoading}
                className="w-full rounded-xl bg-brand text-white text-[15px] font-bold py-3.5 transition disabled:opacity-40 disabled:cursor-not-allowed hover:enabled:bg-brand-ink"
              >
                {submitLoading ? "제출 중..." : "예약(주문) 제출"}
              </button>

              {/* 수동 제작 안내 */}
              <p className="text-[12px] text-ink3 text-center">
                주문 후 담당자가 확인해 제작·발송합니다. 진행 상황은 주문 목록에서 확인하세요.
              </p>
            </form>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
