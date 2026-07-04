/** 판촉물 브랜드 플레이스홀더 — 사진이 없거나 죽은 URL일 때 의도된 디자인 카드로 표시.
 *  브랜드 그라디언트(brand→brand-ink) + 카테고리/샘플명 타이포. 부정 문구 0 (§6c).
 *  사용처: /promotion 목록 썸네일 폴백 + /promotion/[sampleId] 대표 이미지 폴백. */
export function SamplePlaceholder({ name, category }: { name: string; category: string }) {
  return (
    <div className="w-full h-full flex flex-col items-center justify-center gap-1.5 bg-gradient-to-br from-brand to-brand-ink px-4 text-center">
      <span className="text-[11px] font-semibold tracking-wide text-white/70">{category}</span>
      <span className="text-[15px] font-bold leading-5 text-white line-clamp-2 break-keep">{name}</span>
      <span className="mt-1.5 text-[10px] font-extrabold tracking-[0.2em] text-white/45">INPA</span>
    </div>
  );
}
