#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROLES = new Set(["cover", "inline", "diagram", "product-screen"]);
const SOURCE_TYPES = new Set(["generated-object", "product-capture", "original-diagram", "licensed-photo"]);
const LICENSES = new Set(["project-owned", "generated-for-inpa", "commercial-license"]);
const COVER_BYTES = 200 * 1024;
const INLINE_BYTES = 180 * 1024;

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

function parseWebpDimensions(buffer) {
  if (buffer.length < 20 || buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WEBP") {
    throw new Error("유효한 RIFF WebP 헤더가 아닙니다");
  }
  for (let offset = 12; offset + 8 <= buffer.length;) {
    const kind = buffer.toString("ascii", offset, offset + 4);
    const size = buffer.readUInt32LE(offset + 4);
    const data = offset + 8;
    if (data + size > buffer.length) throw new Error(`${kind} 청크가 파일 범위를 벗어납니다`);
    if (kind === "VP8X") {
      if (size < 10) throw new Error("VP8X 청크가 너무 짧습니다");
      return {
        width: buffer.readUIntLE(data + 4, 3) + 1,
        height: buffer.readUIntLE(data + 7, 3) + 1,
      };
    }
    if (kind === "VP8L") {
      if (size < 5 || buffer[data] !== 0x2f) throw new Error("VP8L 헤더가 올바르지 않습니다");
      const b1 = buffer[data + 1];
      const b2 = buffer[data + 2];
      const b3 = buffer[data + 3];
      const b4 = buffer[data + 4];
      return {
        width: 1 + b1 + ((b2 & 0x3f) << 8),
        height: 1 + ((b2 & 0xc0) >> 6) + (b3 << 2) + ((b4 & 0x0f) << 10),
      };
    }
    if (kind === "VP8 ") {
      if (
        size < 10
        || buffer[data + 3] !== 0x9d
        || buffer[data + 4] !== 0x01
        || buffer[data + 5] !== 0x2a
      ) {
        throw new Error("VP8 프레임 헤더가 올바르지 않습니다");
      }
      return {
        width: buffer.readUInt16LE(data + 6) & 0x3fff,
        height: buffer.readUInt16LE(data + 8) & 0x3fff,
      };
    }
    offset = data + size + (size % 2);
  }
  throw new Error("WebP 크기 정보를 찾지 못했습니다");
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

function walkWebps(root) {
  const result = [];
  if (!fs.existsSync(root)) return result;
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile() && entry.name.toLowerCase().endsWith(".webp")) result.push(file);
    }
  };
  visit(root);
  return result;
}

function extractImagePaths(markdown) {
  const withoutFences = markdown.replace(/```[\s\S]*?```|~~~[\s\S]*?~~~/g, "");
  const found = [];
  const inline = /!\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["'][^"']*["'])?\s*\)/g;
  for (const match of withoutFences.matchAll(inline)) found.push(match[1] ?? match[2]);

  const definitions = new Map();
  const definition = /^\s*\[([^\]]+)\]:\s*(?:<([^>]+)>|([^\s]+))/gm;
  for (const match of withoutFences.matchAll(definition)) definitions.set(match[1].trim().toLowerCase(), match[2] ?? match[3]);
  const reference = /!\[[^\]]*\]\[([^\]]+)\]/g;
  for (const match of withoutFences.matchAll(reference)) {
    const destination = definitions.get(match[1].trim().toLowerCase());
    if (destination) found.push(destination);
  }
  const htmlImage = /<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/gi;
  for (const match of withoutFences.matchAll(htmlImage)) found.push(match[1]);
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

export function validateBlogRelease({ frontendRoot, contentRoot }) {
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
  }
  if (posts.length !== 20) errors.push(`릴리스 원고는 정확히 20편이어야 합니다 (현재 ${posts.length}편)`);

  const byPath = new Map();
  const coverHashes = new Map();
  const digestByPath = new Map();
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
    let dimensions;
    try {
      dimensions = parseWebpDimensions(bytes);
    } catch (error) {
      errors.push(`${assetPath}: WebP를 읽을 수 없습니다 (${error.message})`);
      continue;
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

  const coverRecords = manifest.filter((record) => record?.role === "cover" && safeAssetPath(record.path));
  if (coverRecords.length !== 20) errors.push(`대표 이미지 manifest 항목은 정확히 20개여야 합니다 (현재 ${coverRecords.length}개)`);

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
  }

  for (const [assetPath, record] of byPath) {
    const expected = actualUsage.get(assetPath) ?? new Set();
    const declared = new Set(Array.isArray(record.used_by) ? record.used_by : []);
    for (const slug of expected) if (!declared.has(slug)) errors.push(`${assetPath}: used_by에 실제 사용 원고가 빠졌습니다 (${slug})`);
    for (const slug of declared) if (!expected.has(slug)) errors.push(`${assetPath}: used_by에 실제로 사용하지 않는 원고가 있습니다 (${slug})`);
  }

  const declaredFiles = new Set([...byPath.keys()].map((assetPath) => path.resolve(assetFile(frontendRoot, assetPath))));
  for (const file of walkWebps(assetsRoot)) {
    if (!declaredFiles.has(path.resolve(file))) {
      const relative = path.relative(path.join(frontendRoot, "public"), file).split(path.sep).join("/");
      errors.push(`manifest에 선언되지 않은 WebP가 있습니다 (/${relative})`);
    }
  }

  return { errors, postCount: posts.length, coverCount: coverRecords.length, assetCount: manifest.length };
}

function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`블로그 이미지 릴리스 검사 실패\n- ${error.message}`);
    process.exitCode = 1;
    return;
  }
  const result = validateBlogRelease(options);
  if (result.errors.length) {
    console.error(`블로그 이미지 릴리스 검사 실패 (${result.errors.length}건)`);
    for (const error of result.errors) console.error(`- ${error}`);
    process.exitCode = 1;
    return;
  }
  console.log(`블로그 이미지 릴리스 검사 통과: 원고 ${result.postCount}편, 대표 이미지 ${result.coverCount}개, 전체 자산 ${result.assetCount}개`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();

export { parseWebpDimensions };
