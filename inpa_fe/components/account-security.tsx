"use client";

// 계정 보안 — 비밀번호 변경 + 회원 탈퇴.
// ★ 구글 전용 가입자(hasPassword=false): 비번변경 숨김, 탈퇴는 가입 이메일 입력으로 확인(삭제권 보장).

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Card } from "@/components/ui";
import { changePassword, withdrawAccount, ApiError } from "@/lib/api";

export function AccountSecurity({ hasPassword, email }: { hasPassword: boolean; email: string }) {
  const router = useRouter();
  // 비밀번호 변경
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [newPw2, setNewPw2] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [pwMsg, setPwMsg] = useState<string | null>(null);
  // 회원 탈퇴
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [confirmInput, setConfirmInput] = useState("");
  const [wdBusy, setWdBusy] = useState(false);
  const [wdErr, setWdErr] = useState<string | null>(null);

  const inputCls =
    "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-ink placeholder:text-muted outline-none focus:border-brand transition";

  async function submitPassword() {
    setPwMsg(null);
    if (newPw.length < 8) { setPwMsg("새 비밀번호는 8자 이상이어야 해요."); return; }
    if (newPw !== newPw2) { setPwMsg("새 비밀번호가 일치하지 않아요."); return; }
    setPwBusy(true);
    try {
      await changePassword(oldPw, newPw);
      setPwMsg("비밀번호가 변경되었어요.");
      setOldPw(""); setNewPw(""); setNewPw2("");
    } catch (e) {
      setPwMsg(e instanceof ApiError ? e.message : "변경에 실패했어요.");
    } finally {
      setPwBusy(false);
    }
  }

  async function submitWithdraw() {
    setWdErr(null);
    setWdBusy(true);
    try {
      await withdrawAccount(hasPassword ? { password: confirmInput } : { confirm: confirmInput });
      router.push("/login");
    } catch (e) {
      setWdErr(e instanceof ApiError ? e.message : "탈퇴에 실패했어요.");
    } finally {
      setWdBusy(false);
    }
  }

  return (
    <>
      {/* 비밀번호 변경 */}
      <Card className="px-5 py-4">
        <h2 className="text-[15px] font-bold text-ink">비밀번호 변경</h2>
        {hasPassword ? (
          <div className="mt-3 space-y-2.5">
            <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} placeholder="현재 비밀번호" autoComplete="current-password" className={inputCls} />
            <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="새 비밀번호 (8자 이상)" autoComplete="new-password" className={inputCls} />
            <input type="password" value={newPw2} onChange={(e) => setNewPw2(e.target.value)} placeholder="새 비밀번호 확인" autoComplete="new-password" className={inputCls} />
            {pwMsg && <p className="text-[13px] text-ink2">{pwMsg}</p>}
            <button onClick={submitPassword} disabled={pwBusy || !oldPw || !newPw} className="rounded-xl bg-brand text-white text-[14px] font-bold px-4 py-2.5 disabled:opacity-60">
              {pwBusy ? "변경 중…" : "비밀번호 변경"}
            </button>
          </div>
        ) : (
          <p className="mt-2 text-[13px] text-ink3 leading-5">구글 로그인 계정이라 비밀번호가 없어요. 보안은 구글 계정에서 관리하세요.</p>
        )}
      </Card>

      {/* 회원 탈퇴 */}
      <Card className="px-5 py-4">
        <h2 className="text-[15px] font-bold text-danger">회원 탈퇴</h2>
        <p className="mt-1 text-[13px] text-ink3 leading-5">
          탈퇴하면 내 고객·분석·일정 등 <b>모든 데이터가 즉시 삭제</b>되고 되돌릴 수 없어요.
        </p>
        {!withdrawOpen ? (
          <button onClick={() => setWithdrawOpen(true)} className="mt-3 rounded-xl border border-danger text-danger text-[14px] font-semibold px-4 py-2.5 hover:bg-danger-tint transition">
            회원 탈퇴
          </button>
        ) : (
          <div className="mt-3 space-y-2.5">
            <p className="text-[13px] text-ink2">
              {hasPassword ? "확인을 위해 비밀번호를 입력하세요." : <>확인을 위해 가입 이메일 <b>{email}</b> 을(를) 입력하세요.</>}
            </p>
            <input
              type={hasPassword ? "password" : "email"}
              value={confirmInput}
              onChange={(e) => setConfirmInput(e.target.value)}
              placeholder={hasPassword ? "비밀번호" : "가입 이메일"}
              autoComplete="off"
              className={inputCls}
            />
            {wdErr && <p className="text-[13px] text-danger">{wdErr}</p>}
            <div className="flex gap-2">
              <button onClick={() => { setWithdrawOpen(false); setConfirmInput(""); setWdErr(null); }} className="flex-1 rounded-xl border border-line text-ink2 text-[14px] font-semibold py-2.5 hover:bg-surface2">
                취소
              </button>
              <button onClick={submitWithdraw} disabled={wdBusy || !confirmInput} className="flex-1 rounded-xl bg-danger text-white text-[14px] font-bold py-2.5 disabled:opacity-60">
                {wdBusy ? "처리 중…" : "탈퇴하기"}
              </button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
