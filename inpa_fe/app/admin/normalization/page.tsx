"use client";

// ════════════════════════════════════════════════════════════════════════════
// /admin/normalization — 정규화 검수 화면 (3탭).
//   1) 미매칭 큐: OCR이 표준에 못 붙인 원문 → 표준 담보 선택해 사전 등록.
//      ★ 2026-07-09 계약 정합 픽스: payload {unmatched_log_id, std_detail_id, confidence}
//        (과거 {unmatched_id, standard_name} 는 BE 400 — 동작 불능 버그였음).
//   2) 이상 신고: 설계사의 "담보 위치가 이상해요" 요청 검수 → 승인(사전 반영 +
//      연결 정정) / 반려. 승인 응답의 교정 수·부분문자열 충돌 경고 표시.
//   3) 기존 사전: 등록된 별칭 조회/삭제 (BE 필드명 std_detail_name/company 정합).
// ════════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback, useMemo } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import {
  adminListUnmatched,
  adminMapNormalization,
  adminListNormalizationDict,
  adminDeleteNormalizationDict,
  adminListNormalizationLeaves,
  adminListCoverageFlags,
  adminResolveCoverageFlag,
  adminGetNormalizationAccuracy,
  type UnmatchedLogItem,
  type NormalizationDictItem,
  type NormalizationLeaf,
  type CoverageFlagItem,
  type CoverageFlagResolveResult,
  type NormalizationAccuracy,
} from "@/lib/adminApi";
import { Card } from "@/components/ui";

// ── 골든셋 정확도 기준선 카드 (프리런치 리뷰 #18) ───────────────────────────
function AccuracyCard() {
  const [data, setData] = useState<NormalizationAccuracy | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminGetNormalizationAccuracy()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Card className="p-5 mb-5">
        <div className="text-[13px] text-ink3">정확도 기준선을 불러오는 중...</div>
      </Card>
    );
  }
  if (!data) {
    return (
      <Card className="p-5 mb-5">
        <div className="text-[13px] text-ink3">
          정확도 기준선을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.
        </div>
      </Card>
    );
  }

  const pct = (data.accuracy * 100).toFixed(1);
  const anchorsOk = data.anchor_passed === data.anchor_total;

  return (
    <Card className="p-5 mb-5">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-[14px] font-bold text-ink">키워드 매처 재현율 기준선</h2>
        <span className="text-[11px] text-ink3">
          골든셋(자체 사전 + 회귀 앵커) 대비 키워드 자동매칭 재현율
        </span>
      </div>
      <p className="text-[11px] text-ink3 mb-3 leading-relaxed">
        실제 증권 분석은 AI(Claude)와 검수 사전까지 함께 써서 이 수치보다 정확합니다.
        이 값은 키워드 자동매칭만 따로 떼어 사전·매처를 바꿀 때 정확도가 떨어지는지
        감시하는 회귀 지표입니다. 낮게 보이는 항목 상당수는 세분류 담보라 키워드만으로는
        구분이 어려운 경우이며(회귀 앵커는 반드시 통과), 실제 분석에는 영향이 없습니다.
      </p>
      <div className="flex flex-wrap items-center gap-6">
        <div>
          <div className="text-[28px] font-extrabold text-ink tnum">{pct}%</div>
          <div className="text-[11px] text-ink3 tnum">
            {data.passed} / {data.total}건 일치 · 기준선 {(data.min_accuracy * 100).toFixed(0)}%
          </div>
        </div>
        <div
          className={`text-[12px] font-semibold rounded-full px-3 py-1.5 ${
            anchorsOk
              ? "bg-emerald-50 text-emerald-700"
              : "bg-rose-50 text-rose-700"
          }`}
        >
          회귀 앵커 {data.anchor_passed} / {data.anchor_total}건 통과
        </div>
      </div>
      {data.sample_failures.length > 0 && (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-[12px] font-semibold text-brand"
          >
            {expanded ? "일치하지 않는 항목 접기" : `일치하지 않는 항목 보기 (${data.sample_failures.length}건)`}
          </button>
          {expanded && (
            <div className="mt-2 max-h-64 overflow-y-auto rounded-xl border border-line divide-y divide-line">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-line text-ink3">
                    <th className="text-left px-3 py-2 font-semibold">회사</th>
                    <th className="text-left px-3 py-2 font-semibold">원문</th>
                    <th className="text-left px-3 py-2 font-semibold">기대 표준 담보</th>
                    <th className="text-left px-3 py-2 font-semibold">실제 매칭</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.sample_failures.map((f, i) => (
                    <tr key={i}>
                      <td className="px-3 py-2 text-ink3">{companyLabel(f.company)}</td>
                      <td className="px-3 py-2 text-ink font-medium">{f.raw_name}</td>
                      <td className="px-3 py-2 text-ink3">{f.expected}</td>
                      <td className="px-3 py-2 text-ink3">{f.got ?? "매칭 안 됨"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ── 보험사 코드 → 라벨 (core/ocr/ocrdata.py index 기준: 손해 0~, 생명 200+) ──
const LOSS_COMPANIES = [
  "롯데손해", "메리츠화재", "삼성화재", "에이스손해", "우체국보험", "하나손해",
  "한화손해", "현대해상", "흥국화재", "AIG손해", "AXA손해", "DB손해", "KB손해",
  "LIG손해", "MG손해", "NH농협손해",
];
const LIFE_COMPANIES = [
  "교보라이프플래닛", "교보생명", "동양생명", "라이나생명", "메트라이프생명",
  "미래에셋생명", "삼성생명", "신한생명", "오렌지라이프생명", "처브라이프생명",
  "푸르덴셜생명", "푸본현대생명", "하나생명", "한화생명", "흥국생명", "ABL생명",
  "AIA생명", "BNP파리바카디프생명", "DB생명", "DGB생명", "KB생명", "KDB생명",
  "NH농협생명",
];
function companyLabel(code: number | null | undefined): string {
  if (code === null || code === undefined || code < 0) return "미상";
  if (code >= 200) return LIFE_COMPANIES[code - 200] ?? `코드 ${code}`;
  return LOSS_COMPANIES[code] ?? `코드 ${code}`;
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("ko-KR");
  } catch {
    return iso;
  }
}

// ── 표준 담보 선택기 (미매칭 매핑 패널 + 이상 신고 패널 공용) ────────────────
function LeafPicker({
  leaves,
  selectedId,
  onSelect,
}: {
  leaves: NormalizationLeaf[] | null;
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    if (!leaves) return [];
    const needle = q.trim();
    if (!needle) return leaves;
    return leaves.filter(
      (l) =>
        l.name.includes(needle) ||
        l.category_name.includes(needle) ||
        l.sub_category_name.includes(needle)
    );
  }, [leaves, q]);

  return (
    <div>
      <label className="block text-[12px] font-semibold text-ink3 mb-1">표준 담보 선택</label>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="담보명 검색 (예: 암진단)"
        className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-muted outline-none focus:border-brand"
      />
      <div className="mt-2 max-h-56 overflow-y-auto rounded-xl border border-line divide-y divide-line">
        {leaves === null && (
          <div className="px-3 py-4 text-center text-[12px] text-ink3">불러오는 중...</div>
        )}
        {leaves !== null && filtered.length === 0 && (
          <div className="px-3 py-4 text-center text-[12px] text-ink3">검색 결과가 없어요.</div>
        )}
        {filtered.map((l) => (
          <button
            key={l.id}
            type="button"
            onClick={() => onSelect(l.id)}
            className={`w-full text-left px-3 py-2 transition ${
              selectedId === l.id ? "bg-brand-soft" : "hover:bg-surface2"
            }`}
          >
            <span className="text-[13px] font-semibold text-ink">{l.name}</span>
            <span className="ml-2 text-[11px] text-ink3">
              {l.category_name.replace("[표준] ", "")} · {l.sub_category_name}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function AdminNormalizationPage() {
  const ready = useAdminGuard();

  const [tab, setTab] = useState<"unmatched" | "flags" | "dict">("unmatched");

  // ?tab= 딥링크 (대시보드 카드 → 이상 신고 탭). useSearchParams Suspense 회피를 위해
  // 클라이언트 전용으로 window.location.search 를 읽는다(/customers ?stage= 하우스 패턴).
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (t === "unmatched" || t === "flags" || t === "dict") setTab(t);
  }, []);

  // 표준 담보 leaf (선택기 공용 — 1회 로드)
  const [leaves, setLeaves] = useState<NormalizationLeaf[] | null>(null);

  // Unmatched
  const [unmatched, setUnmatched] = useState<UnmatchedLogItem[]>([]);
  const [unmatchedPage, setUnmatchedPage] = useState(1);
  const [unmatchedTotal, setUnmatchedTotal] = useState(0);
  const [unmatchedHasNext, setUnmatchedHasNext] = useState(false);
  const [unmatchedLoading, setUnmatchedLoading] = useState(false);

  const [selectedUnmatched, setSelectedUnmatched] = useState<UnmatchedLogItem | null>(null);
  const [mapLeafId, setMapLeafId] = useState<number | null>(null);
  const [mapping, setMapping] = useState(false);

  // Flags (이상 신고)
  const [flags, setFlags] = useState<CoverageFlagItem[]>([]);
  const [flagPage, setFlagPage] = useState(1);
  const [flagTotal, setFlagTotal] = useState(0);
  const [flagHasNext, setFlagHasNext] = useState(false);
  const [flagLoading, setFlagLoading] = useState(false);
  const [flagStatusFilter, setFlagStatusFilter] = useState<"open" | "all">("open");

  const [selectedFlag, setSelectedFlag] = useState<CoverageFlagItem | null>(null);
  const [flagLeafId, setFlagLeafId] = useState<number | null>(null);
  const [flagRawName, setFlagRawName] = useState("");
  const [flagMemo, setFlagMemo] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolveResult, setResolveResult] = useState<CoverageFlagResolveResult | null>(null);

  // Dict
  const [dictItems, setDictItems] = useState<NormalizationDictItem[]>([]);
  const [dictPage, setDictPage] = useState(1);
  const [dictTotal, setDictTotal] = useState(0);
  const [dictHasNext, setDictHasNext] = useState(false);
  const [dictLoading, setDictLoading] = useState(false);
  const [dictQ, setDictQ] = useState("");

  const fetchUnmatched = useCallback(async () => {
    setUnmatchedLoading(true);
    try {
      const res = await adminListUnmatched({ page: unmatchedPage });
      setUnmatched(res.results);
      setUnmatchedTotal(res.count);
      setUnmatchedHasNext(!!res.next);
    } catch {
      /* 무시 */
    } finally {
      setUnmatchedLoading(false);
    }
  }, [unmatchedPage]);

  const fetchFlags = useCallback(async () => {
    setFlagLoading(true);
    try {
      const res = await adminListCoverageFlags({ page: flagPage, status: flagStatusFilter });
      setFlags(res.results);
      setFlagTotal(res.count);
      setFlagHasNext(!!res.next);
    } catch {
      /* 무시 */
    } finally {
      setFlagLoading(false);
    }
  }, [flagPage, flagStatusFilter]);

  const fetchDict = useCallback(async () => {
    setDictLoading(true);
    try {
      const res = await adminListNormalizationDict({ page: dictPage, q: dictQ || undefined });
      setDictItems(res.results);
      setDictTotal(res.count);
      setDictHasNext(!!res.next);
    } catch {
      /* 무시 */
    } finally {
      setDictLoading(false);
    }
  }, [dictPage, dictQ]);

  useEffect(() => { if (ready) fetchUnmatched(); }, [ready, fetchUnmatched]);
  useEffect(() => { if (ready) fetchFlags(); }, [ready, fetchFlags]);
  useEffect(() => { if (ready && tab === "dict") fetchDict(); }, [ready, tab, fetchDict]);
  useEffect(() => {
    if (!ready) return;
    adminListNormalizationLeaves()
      .then(setLeaves)
      .catch(() => setLeaves([]));
  }, [ready]);

  function openFlagPanel(f: CoverageFlagItem) {
    setSelectedFlag(f);
    setFlagLeafId(null);
    setFlagRawName(f.raw_name_snapshot);
    setFlagMemo("");
    setResolveResult(null);
  }

  async function handleMap() {
    if (!selectedUnmatched || mapLeafId == null) return;
    setMapping(true);
    try {
      await adminMapNormalization({
        unmatched_log_id: selectedUnmatched.id,
        std_detail_id: mapLeafId,
      });
      setSelectedUnmatched(null);
      setMapLeafId(null);
      await fetchUnmatched();
    } catch {
      alert("매핑 등록에 실패했어요.");
    } finally {
      setMapping(false);
    }
  }

  async function handleResolve(action: "accept" | "reject") {
    if (!selectedFlag) return;
    if (action === "accept" && flagLeafId == null) return;
    setResolving(true);
    try {
      const res = await adminResolveCoverageFlag(
        selectedFlag.id,
        action === "accept"
          ? {
              action,
              std_detail_id: flagLeafId as number,
              ...(flagRawName.trim() ? { raw_name: flagRawName.trim() } : {}),
              ...(flagMemo.trim() ? { memo: flagMemo.trim() } : {}),
            }
          : { action, ...(flagMemo.trim() ? { memo: flagMemo.trim() } : {}) }
      );
      setResolveResult(res);
      await fetchFlags();
    } catch {
      alert("처리에 실패했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setResolving(false);
    }
  }

  async function handleDeleteDict(id: number) {
    if (!confirm("삭제하시겠어요? 이 매핑이 제거됩니다.")) return;
    try {
      await adminDeleteNormalizationDict(id);
      await fetchDict();
    } catch {
      alert("삭제에 실패했어요.");
    }
  }

  if (!ready) return null;

  const flagStatusLabel: Record<string, string> = {
    open: "대기",
    accepted: "반영",
    rejected: "반려",
  };

  return (
    <div className="p-6">
      <h1 className="text-[22px] font-extrabold text-ink mb-4">정규화 매핑 큐</h1>
      <p className="text-[12px] text-ink3 mb-5">
        증권에서 읽은 담보명을 표준 담보로 매핑합니다. 매핑 후 다음 분석부터 자동 적용됩니다.
      </p>

      <AccuracyCard />

      {/* 탭 */}
      <div className="flex gap-2 mb-5">
        {(["unmatched", "flags", "dict"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-xl text-[13px] font-semibold transition ${
              tab === t ? "bg-brand text-white" : "bg-surface2 text-ink2 hover:bg-line"
            }`}
          >
            {t === "unmatched"
              ? `미매칭 큐 (${unmatchedTotal})`
              : t === "flags"
                ? `이상 신고 (${flagTotal})`
                : `기존 사전 (${dictTotal})`}
          </button>
        ))}
      </div>

      {tab === "unmatched" && (
        <div className="flex gap-5">
          {/* 미매칭 목록 */}
          <div className="flex-1 min-w-0">
            {unmatchedLoading && <div className="text-[14px] text-ink3">불러오는 중...</div>}
            {!unmatchedLoading && (
              <Card>
                <div className="divide-y divide-line">
                  {unmatched.length === 0 && (
                    <div className="px-4 py-8 text-center text-[13px] text-ink3">
                      미매칭 항목이 없어요. 모두 처리됐습니다.
                    </div>
                  )}
                  {unmatched.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => { setSelectedUnmatched(item); setMapLeafId(null); }}
                      className={`w-full text-left px-4 py-3.5 hover:bg-surface2 transition ${
                        selectedUnmatched?.id === item.id ? "bg-brand-soft" : ""
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-[14px] font-bold text-ink">{item.raw_name}</span>
                        <span className="text-[11px] text-ink3">{companyLabel(item.company)}</span>
                        <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-surface2 text-ink3 tnum">
                          {item.occurrence}회
                        </span>
                        {item.resolved && (
                          <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-emerald-50 text-emerald-700">
                            처리됨
                          </span>
                        )}
                      </div>
                      {item.sample_ctx && (
                        <div className="text-[11px] text-muted truncate">{item.sample_ctx}</div>
                      )}
                    </button>
                  ))}
                </div>
              </Card>
            )}
            <div className="flex gap-3 mt-3 justify-center">
              {unmatchedPage > 1 && (
                <button onClick={() => setUnmatchedPage((p) => p - 1)} className="text-[13px] font-semibold text-brand">← 이전</button>
              )}
              <span className="text-[13px] text-ink3 tnum">페이지 {unmatchedPage}</span>
              {unmatchedHasNext && (
                <button onClick={() => setUnmatchedPage((p) => p + 1)} className="text-[13px] font-semibold text-brand">다음 →</button>
              )}
            </div>
          </div>

          {/* 매핑 패널 */}
          {selectedUnmatched && (
            <div className="w-96 shrink-0">
              <Card className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-[14px] font-bold text-ink">매핑 등록</h2>
                  <button onClick={() => setSelectedUnmatched(null)} className="text-ink3 text-[18px] leading-none hover:text-ink">×</button>
                </div>
                <div className="bg-surface2 rounded-xl px-3 py-2.5 mb-4">
                  <div className="text-[12px] text-ink3 mb-1">원본 이름</div>
                  <div className="text-[14px] font-bold text-ink">{selectedUnmatched.raw_name}</div>
                  <div className="text-[11px] text-ink3 mt-0.5">
                    {companyLabel(selectedUnmatched.company)} · {selectedUnmatched.occurrence}회
                  </div>
                </div>
                <LeafPicker leaves={leaves} selectedId={mapLeafId} onSelect={setMapLeafId} />
                <button
                  onClick={handleMap}
                  disabled={mapping || mapLeafId == null}
                  className="mt-4 w-full rounded-xl bg-brand text-white text-[13px] font-bold py-2.5 disabled:opacity-50 transition"
                >
                  {mapping ? "등록 중..." : "매핑 등록"}
                </button>
              </Card>
            </div>
          )}
        </div>
      )}

      {tab === "flags" && (
        <div className="flex gap-5">
          {/* 신고 목록 */}
          <div className="flex-1 min-w-0">
            <div className="flex gap-2 mb-3">
              {(["open", "all"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => { setFlagStatusFilter(s); setFlagPage(1); setSelectedFlag(null); }}
                  className={`px-3 py-1.5 rounded-full text-[12px] font-semibold border transition ${
                    flagStatusFilter === s
                      ? "bg-brand text-white border-brand"
                      : "bg-surface text-ink2 border-line hover:border-brand"
                  }`}
                >
                  {s === "open" ? "대기만" : "전체"}
                </button>
              ))}
            </div>
            {flagLoading && <div className="text-[14px] text-ink3">불러오는 중...</div>}
            {!flagLoading && (
              <Card>
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]">
                    <thead>
                      <tr className="border-b border-line text-ink3">
                        <th className="text-left px-4 py-3 font-semibold">원문</th>
                        <th className="text-left px-4 py-3 font-semibold">회사</th>
                        <th className="text-left px-4 py-3 font-semibold">메모</th>
                        <th className="text-left px-4 py-3 font-semibold">설계사</th>
                        <th className="text-left px-4 py-3 font-semibold">현재 매핑</th>
                        <th className="text-left px-4 py-3 font-semibold">상태</th>
                        <th className="text-left px-4 py-3 font-semibold">날짜</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {flags.length === 0 && (
                        <tr>
                          <td colSpan={7} className="px-4 py-8 text-center text-ink3">
                            검토할 신고가 없어요. 모두 처리됐습니다.
                          </td>
                        </tr>
                      )}
                      {flags.map((f) => (
                        <tr
                          key={f.id}
                          onClick={() => openFlagPanel(f)}
                          className={`cursor-pointer transition ${
                            selectedFlag?.id === f.id ? "bg-brand-soft" : "hover:bg-surface2"
                          }`}
                        >
                          <td className="px-4 py-3 font-semibold text-ink">
                            {f.raw_name_snapshot || "(원문 없음)"}
                          </td>
                          <td className="px-4 py-3 text-ink3">{companyLabel(f.company)}</td>
                          <td className="px-4 py-3 text-ink3 max-w-48 truncate">{f.note || "-"}</td>
                          <td className="px-4 py-3 text-ink3">{f.planner_email ?? "-"}</td>
                          <td className="px-4 py-3 text-ink3">{f.current_mapping ?? "-"}</td>
                          <td className="px-4 py-3 text-ink3">{flagStatusLabel[f.status] ?? f.status}</td>
                          <td className="px-4 py-3 text-ink3 tnum">{fmtDate(f.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
            <div className="flex gap-3 mt-3 justify-center">
              {flagPage > 1 && (
                <button onClick={() => setFlagPage((p) => p - 1)} className="text-[13px] font-semibold text-brand">← 이전</button>
              )}
              <span className="text-[13px] text-ink3 tnum">페이지 {flagPage}</span>
              {flagHasNext && (
                <button onClick={() => setFlagPage((p) => p + 1)} className="text-[13px] font-semibold text-brand">다음 →</button>
              )}
            </div>
          </div>

          {/* 검수 패널 */}
          {selectedFlag && (
            <div className="w-96 shrink-0">
              <Card className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-[14px] font-bold text-ink">신고 검수</h2>
                  <button onClick={() => setSelectedFlag(null)} className="text-ink3 text-[18px] leading-none hover:text-ink">×</button>
                </div>
                <div className="bg-surface2 rounded-xl px-3 py-2.5 mb-4 space-y-1">
                  <div className="text-[14px] font-bold text-ink">
                    {selectedFlag.raw_name_snapshot || "(원문 없음)"}
                  </div>
                  <div className="text-[11px] text-ink3">
                    {companyLabel(selectedFlag.company)} · 현재 매핑{" "}
                    {selectedFlag.current_mapping ?? "-"} · 고객 {selectedFlag.customer_name ?? "-"}
                  </div>
                  <div className="text-[11px] text-ink3">{selectedFlag.planner_email ?? "-"}</div>
                  {selectedFlag.note && (
                    <div className="text-[12px] text-ink2">설계사 메모: {selectedFlag.note}</div>
                  )}
                </div>

                {resolveResult ? (
                  <div className="space-y-3">
                    <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-[12px] text-emerald-800">
                      {resolveResult.flag.status === "accepted" ? (
                        <>
                          반영 완료. 연결 정정 {resolveResult.relinked ?? 0}건
                          {resolveResult.dict_created !== undefined && (
                            <> · 사전 별칭 {resolveResult.dict_created ? "신규 등록" : resolveResult.dict_id ? "기존 갱신" : "등록 생략(회사/원문 정보 부족)"}</>
                          )}
                        </>
                      ) : (
                        "반려 처리했어요."
                      )}
                    </div>
                    {(resolveResult.warnings?.length ?? 0) > 0 && (
                      <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800 space-y-1">
                        {resolveResult.warnings!.map((w, i) => (
                          <div key={i}>{w}</div>
                        ))}
                      </div>
                    )}
                    <button
                      onClick={() => setSelectedFlag(null)}
                      className="w-full rounded-xl border border-line bg-surface text-[13px] font-semibold text-ink2 py-2.5 transition"
                    >
                      닫기
                    </button>
                  </div>
                ) : selectedFlag.status !== "open" ? (
                  <div className="rounded-xl bg-surface2 border border-line px-3 py-2.5 text-[12px] text-ink2">
                    이미 처리된 요청이에요 ({flagStatusLabel[selectedFlag.status]}
                    {selectedFlag.resolution_memo ? ` · ${selectedFlag.resolution_memo}` : ""}).
                  </div>
                ) : (
                  <>
                    <LeafPicker leaves={leaves} selectedId={flagLeafId} onSelect={setFlagLeafId} />
                    <div className="mt-3">
                      <label className="block text-[12px] font-semibold text-ink3 mb-1">
                        사전에 등록할 원문 (수정 가능)
                      </label>
                      <input
                        value={flagRawName}
                        onChange={(e) => setFlagRawName(e.target.value)}
                        maxLength={120}
                        className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                      />
                    </div>
                    <div className="mt-3">
                      <label className="block text-[12px] font-semibold text-ink3 mb-1">
                        처리 메모 (반려 시 권장)
                      </label>
                      <input
                        value={flagMemo}
                        onChange={(e) => setFlagMemo(e.target.value)}
                        maxLength={200}
                        placeholder="예: 현재 매핑이 맞아요"
                        className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-muted outline-none focus:border-brand"
                      />
                    </div>
                    <div className="mt-4 flex gap-2">
                      <button
                        onClick={() => handleResolve("accept")}
                        disabled={resolving || flagLeafId == null}
                        className="flex-1 rounded-xl bg-brand text-white text-[13px] font-bold py-2.5 disabled:opacity-50 transition"
                      >
                        {resolving ? "처리 중..." : "승인(사전 반영)"}
                      </button>
                      <button
                        onClick={() => handleResolve("reject")}
                        disabled={resolving}
                        className="flex-1 rounded-xl border border-line bg-surface text-[13px] font-semibold text-ink2 py-2.5 disabled:opacity-50 transition"
                      >
                        반려
                      </button>
                    </div>
                  </>
                )}
              </Card>
            </div>
          )}
        </div>
      )}

      {tab === "dict" && (
        <div>
          <div className="flex gap-2 mb-4">
            <input
              value={dictQ}
              onChange={(e) => setDictQ(e.target.value)}
              placeholder="원본명 검색"
              className="flex-1 rounded-xl border border-line bg-surface px-4 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>
          {dictLoading && <div className="text-[14px] text-ink3">불러오는 중...</div>}
          {!dictLoading && (
            <>
              <div className="text-[12px] text-ink3 mb-2 tnum">전체 {dictTotal}건</div>
              <Card>
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]">
                    <thead>
                      <tr className="border-b border-line text-ink3">
                        <th className="text-left px-4 py-3 font-semibold">표준 담보명</th>
                        <th className="text-left px-4 py-3 font-semibold">원본명</th>
                        <th className="text-left px-4 py-3 font-semibold">보험사</th>
                        <th className="text-left px-4 py-3 font-semibold">출처</th>
                        <th className="text-left px-4 py-3 font-semibold tnum">조회수</th>
                        <th className="px-4 py-3" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {dictItems.length === 0 && (
                        <tr>
                          <td colSpan={6} className="px-4 py-8 text-center text-ink3">결과가 없어요.</td>
                        </tr>
                      )}
                      {dictItems.map((d) => (
                        <tr key={d.id} className="hover:bg-surface2 transition">
                          <td className="px-4 py-3 font-semibold text-ink">{d.std_detail_name}</td>
                          <td className="px-4 py-3 text-ink3">{d.raw_name}</td>
                          <td className="px-4 py-3 text-ink3">{companyLabel(d.company)}</td>
                          <td className="px-4 py-3 text-ink3">{d.source_display}</td>
                          <td className="px-4 py-3 text-ink3 tnum">{d.hit_count}</td>
                          <td className="px-4 py-3">
                            <button
                              onClick={() => handleDeleteDict(d.id)}
                              className="text-[12px] font-semibold text-danger hover:underline"
                            >
                              삭제
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <div className="flex gap-3 mt-3 justify-center">
                {dictPage > 1 && (
                  <button onClick={() => setDictPage((p) => p - 1)} className="text-[13px] font-semibold text-brand">← 이전</button>
                )}
                <span className="text-[13px] text-ink3 tnum">페이지 {dictPage}</span>
                {dictHasNext && (
                  <button onClick={() => setDictPage((p) => p + 1)} className="text-[13px] font-semibold text-brand">다음 →</button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
