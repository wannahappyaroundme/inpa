"use client";

import { useState, useEffect, useCallback } from "react";
import { useAdminGuard } from "@/lib/useAdminGuard";
import {
  adminListUnmatched,
  adminMapNormalization,
  adminListNormalizationDict,
  adminDeleteNormalizationDict,
  type UnmatchedLogItem,
  type NormalizationDictItem,
} from "@/lib/adminApi";
import { Card } from "@/components/ui";

export default function AdminNormalizationPage() {
  const ready = useAdminGuard();

  const [tab, setTab] = useState<"unmatched" | "dict">("unmatched");

  // Unmatched
  const [unmatched, setUnmatched] = useState<UnmatchedLogItem[]>([]);
  const [unmatchedPage, setUnmatchedPage] = useState(1);
  const [unmatchedTotal, setUnmatchedTotal] = useState(0);
  const [unmatchedHasNext, setUnmatchedHasNext] = useState(false);
  const [unmatchedLoading, setUnmatchedLoading] = useState(false);

  const [selectedUnmatched, setSelectedUnmatched] = useState<UnmatchedLogItem | null>(null);
  const [standardName, setStandardName] = useState("");
  const [mapping, setMapping] = useState(false);

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
  useEffect(() => { if (ready && tab === "dict") fetchDict(); }, [ready, tab, fetchDict]);

  async function handleMap() {
    if (!selectedUnmatched || !standardName.trim()) return;
    setMapping(true);
    try {
      await adminMapNormalization({ unmatched_id: selectedUnmatched.id, standard_name: standardName });
      setSelectedUnmatched(null);
      setStandardName("");
      await fetchUnmatched();
    } catch {
      alert("매핑 등록에 실패했어요.");
    } finally {
      setMapping(false);
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

  return (
    <div className="p-6">
      <h1 className="text-[22px] font-extrabold text-ink mb-4">정규화 매핑 큐</h1>
      <p className="text-[12px] text-ink3 mb-5">
        OCR에서 미매칭된 담보명을 표준 담보로 매핑합니다. 매핑 후 다음 OCR부터 자동 매칭됩니다.
      </p>

      {/* 탭 */}
      <div className="flex gap-2 mb-5">
        {(["unmatched", "dict"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-xl text-[13px] font-semibold transition ${
              tab === t ? "bg-brand text-white" : "bg-surface2 text-ink2 hover:bg-line"
            }`}
          >
            {t === "unmatched" ? `미매칭 큐 (${unmatchedTotal})` : `기존 사전 (${dictTotal})`}
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
                      onClick={() => { setSelectedUnmatched(item); setStandardName(""); }}
                      className={`w-full text-left px-4 py-3.5 hover:bg-surface2 transition ${
                        selectedUnmatched?.id === item.id ? "bg-brand-soft" : ""
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-[14px] font-bold text-ink">{item.raw_name}</span>
                        <span className="text-[11px] text-ink3">{item.insurer}</span>
                        <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-surface2 text-ink3 tnum">
                          {item.count}회
                        </span>
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
            <div className="w-80 shrink-0">
              <Card className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-[14px] font-bold text-ink">매핑 등록</h2>
                  <button onClick={() => setSelectedUnmatched(null)} className="text-ink3 text-[18px] leading-none hover:text-ink">×</button>
                </div>
                <div className="bg-surface2 rounded-xl px-3 py-2.5 mb-4">
                  <div className="text-[12px] text-ink3 mb-1">원본 이름</div>
                  <div className="text-[14px] font-bold text-ink">{selectedUnmatched.raw_name}</div>
                  <div className="text-[11px] text-ink3 mt-0.5">{selectedUnmatched.insurer} · {selectedUnmatched.count}회</div>
                </div>
                <div className="mb-3">
                  <label className="block text-[12px] font-semibold text-ink3 mb-1">표준 담보명</label>
                  <input
                    value={standardName}
                    onChange={(e) => setStandardName(e.target.value)}
                    placeholder="예: 암진단비"
                    className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-brand"
                  />
                </div>
                <button
                  onClick={handleMap}
                  disabled={mapping || !standardName.trim()}
                  className="w-full rounded-xl bg-brand text-white text-[13px] font-bold py-2.5 disabled:opacity-50 transition"
                >
                  {mapping ? "등록 중..." : "매핑 등록"}
                </button>
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
              placeholder="표준명·raw명 검색"
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
                          <td className="px-4 py-3 font-semibold text-ink">{d.standard_name}</td>
                          <td className="px-4 py-3 text-ink3">{d.raw_name}</td>
                          <td className="px-4 py-3 text-ink3">{d.insurer}</td>
                          <td className="px-4 py-3 text-ink3">{d.source}</td>
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
