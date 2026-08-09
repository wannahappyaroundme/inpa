#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import remarkParse from "remark-parse";
import sharp from "sharp";
import { unified } from "unified";

const ROLES = new Set(["cover", "inline", "diagram", "product-screen"]);
const SOURCE_TYPES = new Set(["generated-object", "product-capture", "original-diagram", "licensed-photo"]);
const LICENSES = new Set(["project-owned", "generated-for-inpa", "commercial-license"]);
const COVER_BYTES = 200 * 1024;
const INLINE_BYTES = 180 * 1024;
const LIST_PAGE_BYTES = Math.floor(1.2 * 1024 * 1024);
const DETAIL_PAGE_BYTES = 900 * 1024;
const VISUAL_DUPLICATE_DISTANCE = 4;
const FORBIDDEN_METADATA_CHUNKS = new Set(["EXIF", "XMP ", "ICCP"]);
const KST_PUBLICATION_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$/;
// 2026-08-blog-enrichment-v1에서 승인된 기존 20편의 정적 자산.
// v2는 발행 시각만 바꾸므로 파일 바이트도 계약으로 고정한다.
const PROTECTED_EXISTING_ASSET_HASHES = new Map([
  ["/blog-assets/3대-진단비란-암-뇌-심장/cover.webp", "1301ce93e826c10acd2edae62df7c3a34785c8abf45179aafa33089a130a9ca7"],
  ["/blog-assets/3대-진단비란-암-뇌-심장/diagnosis-three-areas-4697ee3c.webp", "4697ee3c1e7858ddafe9440d08c05fcd5511531d4089ca3c4a5204f1efd72fe8"],
  ["/blog-assets/갱신형-비갱신형-차이/cover.webp", "2bb2b6dd1765e2c92067f34741097c0e4f4464fdce443558b69a9d3639354c2f"],
  ["/blog-assets/갱신형-비갱신형-차이/premium-flow-46d8375d.webp", "46d8375d7318df952b82e08a544ab79ee70a87a8f75ca74ccde644ec635f0091"],
  ["/blog-assets/갱신형-비갱신형-차이/premium-split-screen-ead78c7c.webp", "ead78c7ce6a815f1ca48444c1f07451d34e52205da13fd519a763377973b2c7a"],
  ["/blog-assets/보험-가입-전-확인사항/cover.webp", "4112465838e9988367ec303f17e85b76748009b432fa0f6d410337e5044508e9"],
  ["/blog-assets/보험-가입-전-확인사항/five-questions-2ed62021.webp", "2ed6202123dad2ccf95520bc0ef7507932cf0a36cdde15d0bfc049320e59c2bf"],
  ["/blog-assets/보험-갈아타기-비교/contract-change-checklist-badd0472.webp", "badd0472f98044df3ee21a0d7b4fde6d90705e704bf91d00b4ca9d0e0d9ce0bf"],
  ["/blog-assets/보험-갈아타기-비교/cover.webp", "0d05d9349202f2fdac3bb2f2cbb14a1047394123b8d61362f70dd20894f661c8"],
  ["/blog-assets/보험-갈아타기-비교/neutral-comparison-screen-76f28843.webp", "76f2884392fe20ea177b5488e998f81573c1c7599428b9adcd1b4cec8dd5a060"],
  ["/blog-assets/보험-갈아타기-설계사-순서/cover.webp", "36b97e0a66a5961c50f5b71988980034877f06bd9edf4efa6ee19faa64bad68e"],
  ["/blog-assets/보험-갈아타기-설계사-순서/four-step-review-119a3846.webp", "119a38464172cb02ddf9f0e663245a0c7162836750894ce1614c367d97012724"],
  ["/blog-assets/보험-갈아타기-설계사-순서/neutral-comparison-screen-400f7301.webp", "400f7301b27afe2d97290be6a6e67bf0e8e117f539f02b00be8b84d53161e5f9"],
  ["/blog-assets/보험-상담-준비-체크리스트/cover.webp", "056dd6fd9959fab831d62a463a235d104efbe0a62785f63538fb455e1bbace59"],
  ["/blog-assets/보험-상담-준비-체크리스트/preparation-checklist-52081ad0.webp", "52081ad06e1e12d659c29f1407f32d5eced28f9fa2dbc7e6a6d47193ff242263"],
  ["/blog-assets/보험-상담-후-기록-다음-연락/cover.webp", "ac067fec5fe94152e4fff0400c5b9a0a15645b881e5276d14af490115aedde8b"],
  ["/blog-assets/보험-상담-후-기록-다음-연락/record-next-action-flow-c016afc0.webp", "c016afc010171b7971880aa0bd9edfb4c89183d7db2dab6c3a1d6e357e9c203e"],
  ["/blog-assets/보험-증권-보는-법-3분-체크리스트/analysis-screen-9d10d26f.webp", "9d10d26f12fcd94fc4bf0425ccc511cfa0d8b4a20540afd555411bb99a68deb6"],
  ["/blog-assets/보험-증권-보는-법-3분-체크리스트/cover.webp", "9a4c864225beec7d1f454bd7f538aa685ee4602646c748e499a15cdeec54c2e1"],
  ["/blog-assets/보험-증권-보는-법-3분-체크리스트/policy-five-checks-ca2aa493.webp", "ca2aa4936a3f6e2124d9888574fffaa13ad9c747a015e2e66d23837742639bc5"],
  ["/blog-assets/보험-증권-요청-문자-안내/cover.webp", "b56dd1fa332ff7d8e9f90c6c131de733e785ac3b948b2a7b51ce24fb75f9873f"],
  ["/blog-assets/보험-증권-요청-문자-안내/request-five-points-a19f7f33.webp", "a19f7f330109c8e526ff28cd12befa7598d035d595d3e90a8862c53fe4e541f9"],
  ["/blog-assets/보험-직업급수-확인-순서/cover.webp", "186a6438635efd04ca0d9798e3373a3dd40277588d6f87cdfbf8f6f72a05286d"],
  ["/blog-assets/보험-직업급수-확인-순서/job-grade-flow-1aa003b0.webp", "1aa003b0936dffacc85dd6292d5c67bc51a9d50acb6b479d2ccb42877104e82e"],
  ["/blog-assets/보험나이-계산법-6개월-예시/age-six-month-boundary-de9f39d4.webp", "de9f39d445c65b0be6a958df566510b979364303e52f4dd3e2dd37ad66abc56e"],
  ["/blog-assets/보험나이-계산법-6개월-예시/cover.webp", "c7eb5910d64e7479146fd03a2b36986b37eaf20ceb5c86ecb14974a337321e9c"],
  ["/blog-assets/보험설계사-고객관리표-필수-항목/cover.webp", "f014de8d84687ffd903d0af2e92776bd2128d879ac5da56bcee53d709509fad1"],
  ["/blog-assets/보험설계사-고객관리표-필수-항목/seven-fields-ee30deb5.webp", "ee30deb517a97246dfa290c53ea9c65bb3f754e678db272eeed21f27169eb36e"],
  ["/blog-assets/비교안내서-한눈에-보는-비교표/comparison-document-map-f092e43c.webp", "f092e43c903b283ed0191985c9ffae4359d82a8b574b6609cb59cd507d432a30"],
  ["/blog-assets/비교안내서-한눈에-보는-비교표/cover.webp", "9f5889c19c2ab6fc3840a1498bf141e0dd8b660ee46d338a8a51134b35eea105"],
  ["/blog-assets/비교안내서-한눈에-보는-비교표/official-verification-flow-575849cc.webp", "575849cc3dc876f4190bb86b19b44dd99076f45442ce822e9c0bc892c63f2340"],
  ["/blog-assets/상담-예약-전날-당일-안내/booking-screen-f133e65d.webp", "f133e65d782df2918090f9efefd05380f707b78a5439d7f5250c327320b6adca"],
  ["/blog-assets/상담-예약-전날-당일-안내/cover.webp", "80243b556fe34eb22a3a079dac086fccfe22b70eee4ac719e2ee27e795a6153f"],
  ["/blog-assets/상담-예약률-높이는-문자와-화법/booking-screen-fb312def.webp", "fb312def5f9904f4af470ecda01fa6aba5d05938d402a3ed3637c911f1354808"],
  ["/blog-assets/상담-예약률-높이는-문자와-화법/cover.webp", "b78990e68bfa806b11b5783d53a600400d0c8670268d840110e0def53e8b9ef7"],
  ["/blog-assets/상담-준비에-쫓기던-새내기-하루-각색/cover.webp", "224057e2a211cfb66113d30234d52072b7f9125f82dd9c59710d452154f9ee63"],
  ["/blog-assets/상담-준비에-쫓기던-새내기-하루-각색/workflow-before-after-9b0255d0.webp", "9b0255d00ff0a8ce7e360a58a7dbdf26312f752d2a1a4dc17963cf0b57178ed1"],
  ["/blog-assets/신입-보험설계사-지인-영업-다음-할-일/cover.webp", "34f76c6242156060fcb69fe206d45f26b57d20a34bc74d7f969e32e285e141a8"],
  ["/blog-assets/신입-보험설계사-지인-영업-다음-할-일/referral-flow-930062b1.webp", "930062b1683b28b713bd91992c21e9acf0a1593266f1e26949b289e066e6a536"],
  ["/blog-assets/실손의료비보험-기본-쉽게-짚어보기/cover.webp", "20f9cc38a8ef0c61470d3a195f864c0606846a51afe37dfcc0fd00b4c3d18ccc"],
  ["/blog-assets/실손의료비보험-기본-쉽게-짚어보기/indemnity-duplication-flow-2ee29336.webp", "2ee293365e08ebdf0745a39c0f6ffef4062fd46d90bd5e6205b48cbcad47a43a"],
  ["/blog-assets/실손의료비보험-기본-쉽게-짚어보기/medical-expense-flow-d21248fe.webp", "d21248febd264b03825511f08118aca056449c78df344c0c3e12a9b09b9b65fb"],
  ["/blog-assets/좋은-보험이란/cover.webp", "3a48eece8d14a07b148ab6d61b34913b9dcb10f192a8b8c91a7c7bd398467088"],
  ["/blog-assets/좋은-보험이란/four-fit-questions-c0e6eda5.webp", "c0e6eda52b8270306ae5f2fc6a1dd54ec31fd2edab38a9569b889a8595b9b011"],
  ["/blog-assets/회사마다-보험-담보-이름-다른-이유/cover.webp", "9d10d26f12fcd94fc4bf0425ccc511cfa0d8b4a20540afd555411bb99a68deb6"],
  ["/blog-assets/회사마다-보험-담보-이름-다른-이유/normalization-flow-03c81356.webp", "03c81356e20b6567d4b004527e35dc44a031368d57a3138c5e484ebb9b19f237"],
]);

function verifyProtectedExistingAssetDigests({ slugs, digestByPath, errors }) {
  for (const [assetPath, expectedDigest] of PROTECTED_EXISTING_ASSET_HASHES) {
    const slug = assetPath.split("/")[2];
    if (!slugs.has(slug)) continue;
    if (digestByPath.get(assetPath) !== expectedDigest) {
      errors.push(`${assetPath}: 기존 20편 자산은 승인된 v1 해시를 보존해야 합니다`);
    }
  }
}

const NEW_PRODUCT_CAPTURE_SLUGS = new Set([
  "보험설계사-주간-계획표-고객-단계별-다음-행동",
  "보험설계사-소개-카드-고객-확인사항",
  "보험설계사-월말-복기-영업-숫자",
  "보험설계사-고객-연간-일정-관리법",
  "보험설계사-팀장-일대일-질문",
]);

function verifyNewPostProductCaptures({ posts, byPath, errors }) {
  for (const post of posts) {
    if (!NEW_PRODUCT_CAPTURE_SLUGS.has(post.meta.slug)) continue;
    const productScreens = post.images
      .map((assetPath) => byPath.get(assetPath))
      .filter((record) => record?.role === "product-screen");
    if (productScreens.length !== 1 || productScreens[0].source_type !== "product-capture") {
      errors.push(`${post.filename}: 실제 인파 제품 화면(product-capture)이 정확히 1개 필요합니다`);
    }
  }
}

function parseArgs(argv) {
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const options = {
    frontendRoot: path.resolve(scriptDir, ".."),
    contentRoot: path.resolve(scriptDir, "..", "..", "docs", "blog-content"),
  };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--frontend-root" && argv[index + 1]) {
      options.frontendRoot = path.resolve(argv[++index]);
    } else if (argv[index] === "--content-root" && argv[index + 1]) {
      options.contentRoot = path.resolve(argv[++index]);
    } else {
      throw new Error(`알 수 없는 인자입니다: ${argv[index]}`);
    }
  }
  return options;
}

function inspectWebp(buffer) {
  if (buffer.length < 20 || buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WEBP") {
    throw new Error("유효한 RIFF WebP 헤더가 아닙니다");
  }
  const riffEnd = buffer.readUInt32LE(4) + 8;
  if (riffEnd > buffer.length) throw new Error("RIFF 크기가 파일 범위를 벗어납니다");

  let dimensions = null;
  let hasRasterPayload = false;
  const forbiddenChunks = [];
  for (let offset = 12; offset + 8 <= riffEnd;) {
    const kind = buffer.toString("ascii", offset, offset + 4);
    const size = buffer.readUInt32LE(offset + 4);
    const data = offset + 8;
    if (data + size > riffEnd) throw new Error(`${kind} 청크가 파일 범위를 벗어납니다`);
    if (FORBIDDEN_METADATA_CHUNKS.has(kind)) forbiddenChunks.push(kind.trim());
    if (kind === "VP8X" && !dimensions) {
      if (size < 10) throw new Error("VP8X 청크가 너무 짧습니다");
      dimensions = {
        width: buffer.readUIntLE(data + 4, 3) + 1,
        height: buffer.readUIntLE(data + 7, 3) + 1,
      };
    }
    if (kind === "VP8L" && !dimensions) {
      if (size < 5 || buffer[data] !== 0x2f) throw new Error("VP8L 헤더가 올바르지 않습니다");
      const b1 = buffer[data + 1];
      const b2 = buffer[data + 2];
      const b3 = buffer[data + 3];
      const b4 = buffer[data + 4];
      dimensions = {
        width: 1 + b1 + ((b2 & 0x3f) << 8),
        height: 1 + ((b2 & 0xc0) >> 6) + (b3 << 2) + ((b4 & 0x0f) << 10),
      };
    }
    if (kind === "VP8 " && !dimensions) {
      if (
        size < 10
        || buffer[data + 3] !== 0x9d
        || buffer[data + 4] !== 0x01
        || buffer[data + 5] !== 0x2a
      ) {
        throw new Error("VP8 프레임 헤더가 올바르지 않습니다");
      }
      dimensions = {
        width: buffer.readUInt16LE(data + 6) & 0x3fff,
        height: buffer.readUInt16LE(data + 8) & 0x3fff,
      };
    }
    if (kind === "VP8 " || kind === "VP8L") hasRasterPayload = true;
    offset = data + size + (size % 2);
  }
  if (!dimensions) throw new Error("WebP 크기 정보를 찾지 못했습니다");
  return { dimensions, forbiddenChunks, hasRasterPayload };
}

function parseWebpDimensions(buffer) {
  return inspectWebp(buffer).dimensions;
}

async function perceptualHash(buffer) {
  const { data, info } = await sharp(buffer)
    .resize(9, 8, { fit: "fill" })
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });
  if (info.width !== 9 || info.height !== 8 || info.channels !== 1) {
    throw new Error("시각 해시용 이미지 크기를 만들지 못했습니다");
  }
  let bits = "";
  for (let y = 0; y < 8; y += 1) {
    for (let x = 0; x < 8; x += 1) {
      bits += data[(y * 9) + x] > data[(y * 9) + x + 1] ? "1" : "0";
    }
  }
  return bits;
}

function hammingDistance(left, right) {
  let distance = 0;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) distance += 1;
  }
  return distance;
}

function safeAssetPath(value) {
  if (typeof value !== "string" || !value.startsWith("/blog-assets/") || value.includes("\\") || value.includes("?") || value.includes("#") || value.includes("%")) {
    return false;
  }
  if (value.includes("\0") || path.posix.normalize(value) !== value) return false;
  const parts = value.split("/");
  return !parts.some((part) => part === "." || part === "..");
}

function assetFile(frontendRoot, assetPath) {
  return path.join(frontendRoot, "public", ...assetPath.slice(1).split("/"));
}

function walkAssetFiles(root) {
  const result = [];
  if (!fs.existsSync(root)) return result;
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile()) result.push(file);
    }
  };
  visit(root);
  return result;
}

function extractImagePaths(markdown) {
  const tree = unified().use(remarkParse).parse(markdown);
  const found = [];
  const definitions = new Map();
  const walk = (node, visit) => {
    visit(node);
    if (Array.isArray(node.children)) {
      for (const child of node.children) walk(child, visit);
    }
  };
  walk(tree, (node) => {
    if (node.type === "definition") definitions.set(node.identifier, node.url);
  });
  walk(tree, (node) => {
    if (node.type === "image") found.push(node.url);
    if (node.type === "imageReference") {
      const destination = definitions.get(node.identifier);
      if (destination) found.push(destination);
    }
    if (node.type === "html") {
      const htmlImage = /<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/gi;
      for (const match of node.value.matchAll(htmlImage)) found.push(match[1]);
    }
  });
  return found;
}

function loadPosts(contentRoot, errors) {
  const posts = [];
  if (!fs.existsSync(contentRoot)) {
    errors.push(`원고 폴더가 없습니다: ${contentRoot}`);
    return posts;
  }
  for (const filename of fs.readdirSync(contentRoot).filter((name) => name.endsWith(".md")).sort()) {
    const file = path.join(contentRoot, filename);
    const source = fs.readFileSync(file, "utf8");
    const match = source.match(/<!--\s*blog-meta\s*\n([\s\S]*?)\n-->/);
    if (!match) continue;
    try {
      const meta = JSON.parse(match[1]);
      if (!meta || typeof meta.slug !== "string" || !meta.slug.trim()) {
        errors.push(`${filename}: slug가 없습니다`);
        continue;
      }
      posts.push({ filename, meta, images: extractImagePaths(source) });
    } catch (error) {
      errors.push(`${filename}: blog-meta JSON을 읽을 수 없습니다 (${error.message})`);
    }
  }
  return posts;
}

export async function validateBlogRelease({ frontendRoot, contentRoot }) {
  const errors = [];
  const assetsRoot = path.join(frontendRoot, "public", "blog-assets");
  const manifestPath = path.join(assetsRoot, "manifest.json");
  let manifest = [];
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    if (!Array.isArray(manifest)) {
      errors.push("manifest.json의 최상위 값은 배열이어야 합니다");
      manifest = [];
    }
  } catch (error) {
    errors.push(`manifest.json을 읽을 수 없습니다 (${error.message})`);
  }

  const posts = loadPosts(contentRoot, errors);
  const slugs = new Set();
  for (const post of posts) {
    if (slugs.has(post.meta.slug)) errors.push(`${post.filename}: slug가 중복됩니다 (${post.meta.slug})`);
    slugs.add(post.meta.slug);
    if (
      typeof post.meta.publication_plan_at !== "string"
      || !KST_PUBLICATION_PATTERN.test(post.meta.publication_plan_at)
      || Number.isNaN(Date.parse(post.meta.publication_plan_at))
    ) {
      errors.push(`${post.filename}: publication_plan_at은 +09:00이 포함된 초 단위 시각이어야 합니다`);
    }
  }
  if (posts.length !== 25) errors.push(`릴리스 원고는 정확히 25편이어야 합니다 (현재 ${posts.length}편)`);

  const byPath = new Map();
  const coverHashes = new Map();
  const coverVisualHashes = [];
  const digestByPath = new Map();
  const fileSizeByPath = new Map();
  const actualUsage = new Map();
  const addUsage = (assetPath, slug) => {
    if (!actualUsage.has(assetPath)) actualUsage.set(assetPath, new Set());
    actualUsage.get(assetPath).add(slug);
  };
  for (const post of posts) {
    addUsage(post.meta.cover_asset_path, post.meta.slug);
    for (const imagePath of post.images) addUsage(imagePath, post.meta.slug);
  }

  for (const [index, record] of manifest.entries()) {
    const label = `manifest[${index}]`;
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      errors.push(`${label}: 객체여야 합니다`);
      continue;
    }
    const assetPath = record.path;
    if (!safeAssetPath(assetPath)) {
      errors.push(`${label}: path는 /blog-assets/ 아래의 안전한 로컬 경로여야 합니다 (${String(assetPath)})`);
      continue;
    }
    if (byPath.has(assetPath)) errors.push(`${label}: path가 중복됩니다 (${assetPath})`);
    byPath.set(assetPath, record);
    if (!ROLES.has(record.role)) errors.push(`${assetPath}: role 값이 허용 목록에 없습니다`);
    if (!SOURCE_TYPES.has(record.source_type)) errors.push(`${assetPath}: source_type 값이 허용 목록에 없습니다`);
    if (!LICENSES.has(record.license)) errors.push(`${assetPath}: license 값이 허용 목록에 없습니다`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(record.created_at) || Number.isNaN(Date.parse(`${record.created_at}T00:00:00Z`))) {
      errors.push(`${assetPath}: created_at은 YYYY-MM-DD 날짜여야 합니다`);
    }
    if (record.pii_reviewed !== true) errors.push(`${assetPath}: pii_reviewed는 반드시 true여야 합니다`);
    if (record.rights_reviewed !== true) errors.push(`${assetPath}: rights_reviewed는 반드시 true여야 합니다`);
    if (!Number.isInteger(record.width) || record.width <= 0 || !Number.isInteger(record.height) || record.height <= 0) {
      errors.push(`${assetPath}: width와 height는 양의 정수여야 합니다`);
    }
    if (!Array.isArray(record.used_by) || record.used_by.length === 0 || record.used_by.some((slug) => typeof slug !== "string" || !slugs.has(slug))) {
      errors.push(`${assetPath}: used_by는 존재하는 원고 slug를 하나 이상 가져야 합니다`);
    } else if (new Set(record.used_by).size !== record.used_by.length) {
      errors.push(`${assetPath}: used_by에 중복 slug가 있습니다`);
    }
    if (typeof record.caption !== "string" || !record.caption.trim()) errors.push(`${assetPath}: caption이 필요합니다`);
    if (record.role === "cover") {
      if (record.alt !== "") errors.push(`${assetPath}: 장식용 대표 이미지 alt는 빈 문자열이어야 합니다`);
      if (!assetPath.endsWith("/cover.webp")) errors.push(`${assetPath}: 대표 이미지 파일명은 cover.webp여야 합니다`);
    } else {
      const altLength = typeof record.alt === "string" ? [...record.alt.trim()].length : 0;
      if (altLength < 20 || altLength > 60 || !/[가-힣]/.test(record.alt ?? "")) {
        errors.push(`${assetPath}: 정보 이미지 alt는 한글을 포함한 20~60자여야 합니다`);
      }
    }

    const file = assetFile(frontendRoot, assetPath);
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
      errors.push(`${assetPath}: 파일이 없습니다`);
      continue;
    }
    const bytes = fs.readFileSync(file);
    fileSizeByPath.set(assetPath, bytes.length);
    let inspection;
    try {
      inspection = inspectWebp(bytes);
    } catch (error) {
      errors.push(`${assetPath}: WebP를 읽을 수 없습니다 (${error.message})`);
      continue;
    }
    const { dimensions } = inspection;
    if (inspection.forbiddenChunks.length > 0) {
      errors.push(`${assetPath}: EXIF, XMP, ICC 메타데이터를 제거해야 합니다 (${inspection.forbiddenChunks.join(", ")})`);
    }
    if (!inspection.hasRasterPayload) {
      errors.push(`${assetPath}: 실제 이미지 데이터(VP8 또는 VP8L)가 필요합니다`);
    } else {
      try {
        await sharp(bytes).resize(1, 1, { fit: "fill" }).raw().toBuffer();
      } catch (error) {
        errors.push(`${assetPath}: 실제 이미지 데이터를 해석할 수 없습니다 (${error.message})`);
      }
    }
    if (dimensions.width !== record.width || dimensions.height !== record.height) {
      errors.push(`${assetPath}: manifest 크기 ${record.width}×${record.height}와 실제 WebP 크기 ${dimensions.width}×${dimensions.height}가 다릅니다`);
    }
    const digest = crypto.createHash("sha256").update(bytes).digest("hex");
    digestByPath.set(assetPath, digest);
    if (record.role === "cover") {
      if (dimensions.width !== 1600 || dimensions.height !== 900) errors.push(`${assetPath}: 대표 이미지는 1600×900이어야 합니다`);
      if (bytes.length > COVER_BYTES) errors.push(`${assetPath}: 대표 이미지 용량은 200KB 이하여야 합니다 (${bytes.length} bytes)`);
      if (coverHashes.has(digest)) errors.push(`${assetPath}: 대표 이미지가 바이트 단위로 중복됩니다 (${coverHashes.get(digest)})`);
      else coverHashes.set(digest, assetPath);
      if (inspection.hasRasterPayload) {
        try {
          const visualHash = await perceptualHash(bytes);
          for (const previous of coverVisualHashes) {
            const distance = hammingDistance(visualHash, previous.hash);
            if (distance <= VISUAL_DUPLICATE_DISTANCE) {
              errors.push(`${assetPath}: 대표 이미지가 시각적으로 중복됩니다 (${previous.path}, 거리 ${distance})`);
              break;
            }
          }
          coverVisualHashes.push({ path: assetPath, hash: visualHash });
        } catch (error) {
          errors.push(`${assetPath}: 대표 이미지 시각 검사를 할 수 없습니다 (${error.message})`);
        }
      }
    } else {
      if (Math.max(dimensions.width, dimensions.height) > 1600) errors.push(`${assetPath}: 본문 이미지의 긴 변은 1600px 이하여야 합니다`);
      if (bytes.length > INLINE_BYTES) errors.push(`${assetPath}: 본문 이미지 용량은 180KB 이하여야 합니다 (${bytes.length} bytes)`);
      const filename = path.posix.basename(assetPath);
      const nameMatch = filename.match(/-([0-9a-f]{8})\.webp$/);
      if (!nameMatch || nameMatch[1] !== digest.slice(0, 8)) {
        errors.push(`${assetPath}: 본문 이미지 파일명은 실제 SHA-256 앞 8자리로 끝나야 합니다`);
      }
    }
  }

  verifyProtectedExistingAssetDigests({ slugs, digestByPath, errors });
  verifyNewPostProductCaptures({ posts, byPath, errors });
  const coverRecords = manifest.filter((record) => record?.role === "cover" && safeAssetPath(record.path));
  if (coverRecords.length !== 25) errors.push(`대표 이미지 manifest 항목은 정확히 25개여야 합니다 (현재 ${coverRecords.length}개)`);
  const conservativeListBytes = coverRecords
    .map((record) => fileSizeByPath.get(record.path) ?? 0)
    .sort((a, b) => b - a)
    .slice(0, 12)
    .reduce((sum, bytes) => sum + bytes, 0);
  if (conservativeListBytes > LIST_PAGE_BYTES) {
    errors.push(`목록 대표 이미지 합계는 1.2MB 이하여야 합니다 (${conservativeListBytes} bytes)`);
  }

  for (const post of posts) {
    const cover = post.meta.cover_asset_path;
    const coverDigest = digestByPath.get(cover);
    if (!safeAssetPath(cover)) errors.push(`${post.filename}: cover_asset_path는 /blog-assets/ 아래의 안전한 로컬 경로여야 합니다`);
    else if (!byPath.has(cover)) errors.push(`${post.filename}: 대표 이미지가 manifest에 없습니다 (${cover})`);
    else if (byPath.get(cover).role !== "cover") errors.push(`${post.filename}: cover_asset_path 항목의 role은 cover여야 합니다`);
    for (const imagePath of post.images) {
      if (!safeAssetPath(imagePath)) errors.push(`${post.filename}: 본문 이미지는 /blog-assets/ 아래의 안전한 로컬 경로만 허용합니다 (${imagePath})`);
      else if (!byPath.has(imagePath)) errors.push(`${post.filename}: 본문 이미지가 manifest에 없습니다 (${imagePath})`);
      else if (byPath.get(imagePath).role === "cover") errors.push(`${post.filename}: 본문에서 대표 이미지를 반복 사용하지 마세요 (${imagePath})`);
      else if (coverDigest && digestByPath.get(imagePath) === coverDigest) errors.push(`${post.filename}: 본문 이미지가 같은 글의 대표 이미지와 바이트가 같습니다 (${imagePath})`);
    }
    const detailBytes = [...new Set([cover, ...post.images])]
      .reduce((sum, assetPath) => sum + (fileSizeByPath.get(assetPath) ?? 0), 0);
    if (detailBytes > DETAIL_PAGE_BYTES) {
      errors.push(`${post.filename}: 상세 이미지 합계는 900KB 이하여야 합니다 (${detailBytes} bytes)`);
    }
  }

  for (const [assetPath, record] of byPath) {
    const expected = actualUsage.get(assetPath) ?? new Set();
    const declared = new Set(Array.isArray(record.used_by) ? record.used_by : []);
    for (const slug of expected) if (!declared.has(slug)) errors.push(`${assetPath}: used_by에 실제 사용 원고가 빠졌습니다 (${slug})`);
    for (const slug of declared) if (!expected.has(slug)) errors.push(`${assetPath}: used_by에 실제로 사용하지 않는 원고가 있습니다 (${slug})`);
  }

  const declaredFiles = new Set([...byPath.keys()].map((assetPath) => path.resolve(assetFile(frontendRoot, assetPath))));
  for (const file of walkAssetFiles(assetsRoot)) {
    if (path.resolve(file) === path.resolve(manifestPath)) continue;
    if (!declaredFiles.has(path.resolve(file))) {
      const relative = path.relative(path.join(frontendRoot, "public"), file).split(path.sep).join("/");
      errors.push(`manifest에 선언되지 않은 파일이 있습니다 (/${relative})`);
    }
  }

  return { errors, postCount: posts.length, coverCount: coverRecords.length, assetCount: manifest.length };
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`블로그 이미지 릴리스 검사 실패\n- ${error.message}`);
    process.exitCode = 1;
    return;
  }
  const result = await validateBlogRelease(options);
  if (result.errors.length) {
    console.error(`블로그 이미지 릴리스 검사 실패 (${result.errors.length}건)`);
    for (const error of result.errors) console.error(`- ${error}`);
    process.exitCode = 1;
    return;
  }
  console.log(`블로그 이미지 릴리스 검사 통과: 원고 ${result.postCount}편, 대표 이미지 ${result.coverCount}개, 전체 자산 ${result.assetCount}개`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();

export { parseWebpDimensions, verifyNewPostProductCaptures, verifyProtectedExistingAssetDigests };
