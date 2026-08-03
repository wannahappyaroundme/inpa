"use client";

// UTM/유입 첫터치 캡처(활성화 퍼널 #16) — 공개 랜딩 진입 시 utm_source/medium/campaign
// 쿼리파라미터가 있으면 sessionStorage('inpa_utm')에 최초 1회만 저장한다(덮어쓰기 안 함 =
// first-touch: 그 세션에서 처음 본 유입 태그를 유지). 화면에는 아무 변화도 없다(순수 캡처).
// PII 아님(캠페인 태그) — 위험문자 제거·60자 절단은 BE(RegisterSerializer)가 한 번 더 한다.
import { useEffect } from "react";

import { inferSafeAcquisition, type SafeAcquisition } from "@/lib/acquisition";

const STORAGE_KEY = "inpa_utm";

/** 공개 랜딩(마운트 시 1회) — 이미 저장된 값이 있으면 아무것도 하지 않는다. */
export function useUtmCapture() {
  useEffect(() => {
    try {
      if (sessionStorage.getItem(STORAGE_KEY)) return;
      const captured = inferSafeAcquisition(window.location.search, document.referrer);
      if (Object.keys(captured).length > 0) {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(captured));
      }
    } catch {
      // sessionStorage 접근 불가(프라이빗 모드 등) — 조용히 무시. 가입 흐름에 영향 없음.
    }
  }, []);
}

/**
 * 가입 제출 시 사용 — first-touch(sessionStorage) 우선, 현재 URL은 빈 키만 채우는 폴백.
 * new.inpa.kr → www.inpa.kr 같은 도메인 간 리다이렉트는 쿼리스트링은 보존되지만
 * sessionStorage는 오리진별로 격리되므로, 저장값이 없을 때만 현재 URL 쿼리를 2차 안전망으로 읽는다
 * (현재 URL이 first-touch 값을 덮어쓰지 않도록 저장값을 나중에 얹는다).
 */
export function readCapturedUtm(): SafeAcquisition {
  let result: SafeAcquisition = {};
  try {
    // 1) 현재 URL 쿼리 또는 안전한 유입 분류(폴백)
    result = inferSafeAcquisition(window.location.search, document.referrer);
  } catch {
    // 무시
  }
  try {
    // 2) 저장된 first-touch 값을 위에 얹어 우선(있으면 URL 값을 덮어씀).
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as SafeAcquisition;
      result = { ...result, ...parsed };
    }
  } catch {
    // 무시
  }
  return result;
}
