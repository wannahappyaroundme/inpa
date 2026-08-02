"use client";

import { useState } from "react";
import Image from "next/image";
import { InpaMark } from "@/components/inpa-logo";
import { getBlogAsset } from "@/lib/blog-assets";

type BlogCoverImageProps = {
  src: string | null | undefined;
  categoryLabel: string;
  className?: string;
};

function BlogCoverFallback({ categoryLabel, className }: Pick<BlogCoverImageProps, "categoryLabel" | "className">) {
  return (
    <div
      className={`flex h-full w-full flex-col items-center justify-center gap-2 bg-accent-tint ${className ?? ""}`}
      role="img"
      aria-label={`${categoryLabel} 기본 이미지`}
    >
      <span aria-hidden>
        <InpaMark size={34} title="" />
      </span>
      <span className="text-[12px] font-bold text-brand-ink">{categoryLabel}</span>
    </div>
  );
}

export function BlogCoverImage({ src, categoryLabel, className }: BlogCoverImageProps) {
  const [hasError, setHasError] = useState(false);
  const isOwnedPath = !!src && src.startsWith("/blog-assets/");
  const asset = isOwnedPath && src ? getBlogAsset(src) : undefined;

  if (hasError || !src || (isOwnedPath && !asset)) {
    return <BlogCoverFallback categoryLabel={categoryLabel} className={className} />;
  }

  if (asset) {
    return (
      <div className="relative h-full w-full" style={{ aspectRatio: `${asset.width} / ${asset.height}` }}>
        <Image
          src={asset.path}
          alt=""
          fill
          sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
          className={`object-cover ${className ?? ""}`}
          onError={() => setHasError(true)}
        />
      </div>
    );
  }

  if (/^https?:\/\//.test(src)) {
    // 기존 R2 업로드 커버는 Next 이미지 allowlist 밖일 수 있어 브라우저 lazy loading으로 호환한다.
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt=""
        className={`h-full w-full object-cover ${className ?? ""}`}
        loading="lazy"
        onError={() => setHasError(true)}
      />
    );
  }

  return <BlogCoverFallback categoryLabel={categoryLabel} className={className} />;
}
