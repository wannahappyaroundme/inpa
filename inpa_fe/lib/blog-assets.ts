import manifestJson from "@/public/blog-assets/manifest.json";

export type BlogAssetRole = "cover" | "inline" | "diagram" | "product-screen";

export interface BlogAssetRecord {
  path: string;
  role: BlogAssetRole;
  source_type: "generated-object" | "product-capture" | "original-diagram" | "licensed-photo";
  license: "project-owned" | "generated-for-inpa" | "commercial-license";
  created_at: string;
  used_by: string[];
  pii_reviewed: boolean;
  rights_reviewed: boolean;
  width: number;
  height: number;
  alt: string;
  caption: string;
}

const records = manifestJson as BlogAssetRecord[];
const byPath = new Map(records.map((record) => [record.path, record]));

export const getBlogAsset = (path: string) => byPath.get(path);

export const absoluteSiteUrl = (path: string) => {
  if (/^https?:\/\//.test(path)) return path;
  const site = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.inpa.kr";
  return `${site}${path.startsWith("/") ? path : `/${path}`}`;
};
