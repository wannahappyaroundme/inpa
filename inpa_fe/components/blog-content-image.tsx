import Image from "next/image";
import { getBlogAsset } from "@/lib/blog-assets";

export function BlogContentImage({ src }: { src: string | undefined }) {
  if (!src?.startsWith("/blog-assets/")) return null;

  let path = src;
  try {
    path = decodeURIComponent(src);
  } catch {
    // malformed URL은 manifest에 없으므로 이미지 없이 남긴다.
  }
  const asset = getBlogAsset(path);
  if (!asset) return null;
  const isProductScreen = asset.role === "product-screen";

  return (
    <figure
      className={`my-6 ${isProductScreen ? "rounded-2xl bg-surface2 p-3 sm:p-4" : ""}`}
      data-asset-role={asset.role}
    >
      <Image
        src={asset.path}
        alt={asset.alt}
        width={asset.width}
        height={asset.height}
        sizes="(max-width: 768px) 100vw, 680px"
        className="h-auto w-full rounded-xl border border-line"
      />
      {asset.caption && (
        <figcaption className="mt-2 text-center text-[13px] leading-6 text-ink3">
          {isProductScreen && (
            <span className="mr-2 inline-flex rounded-full bg-accent-tint px-2 py-0.5 text-[11px] font-bold text-brand">
              화면 예시
            </span>
          )}
          {asset.caption}
        </figcaption>
      )}
    </figure>
  );
}
