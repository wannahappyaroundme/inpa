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

  return (
    <figure className="my-6">
      <Image
        src={asset.path}
        alt={asset.alt}
        width={asset.width}
        height={asset.height}
        sizes="(max-width: 768px) 100vw, 680px"
        className="h-auto w-full rounded-xl border border-line"
      />
      {asset.caption && <figcaption className="mt-2 text-center text-[13px] leading-6 text-ink3">{asset.caption}</figcaption>}
    </figure>
  );
}
