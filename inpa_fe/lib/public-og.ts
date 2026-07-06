// 공개 토큰 라우트(b/c/d/p/s) 공통 정적 OG 메타 빌더.
// - 카톡/SNS 미리보기용 라우트별 title/description(고객 대면·혜택+다음 행동)만 다르고 나머지는 동일.
// - robots noindex: 고객 정보가 오가는 공개 링크는 검색엔진 수집 차단(5종 공통 원칙).
// - og:image = 전역 app/opengraph-image.jpg 재사용(새 에셋 0). 자식 레이아웃이 openGraph 를
//   정의하면 루트의 파일 컨벤션 이미지가 상속되지 않아(객체 통째 교체) 여기서 명시 참조한다.
//   절대 URL 은 루트 layout 의 metadataBase(NEXT_PUBLIC_SITE_URL) 기준으로 해석된다.
import type { Metadata } from "next";

const OG_IMAGE = { url: "/opengraph-image.jpg", width: 1200, height: 630 };

/** 라우트 전용 OG 이미지가 있으면 세 번째 인자로 public/ 경로를 넘긴다(예: "/og-self-diagnosis.jpeg"). */
export function publicTokenMetadata(
  title: string,
  description: string,
  imageUrl?: string,
): Metadata {
  const image = imageUrl ? { url: imageUrl, width: 1200, height: 630 } : OG_IMAGE;
  return {
    title: { absolute: title },
    description,
    robots: { index: false, follow: false },
    openGraph: {
      type: "website",
      locale: "ko_KR",
      siteName: "인파(Inpa)",
      title,
      description,
      images: [image],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [image.url],
    },
  };
}
