#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const COMMON_TOKENS = new Set([
  "보험설계사", "보험", "고객", "확인", "방법", "정리", "인파",
]);
const BOILERPLATE_H2_HEADINGS = new Set([
  "흔히 놓치는 점",
  "보내기 전 저장용 체크리스트",
  "저장용 체크리스트",
  "상담 전 저장용 체크리스트",
]);
const TITLE_THRESHOLD = 0.72;
const BODY_CONTAINMENT_THRESHOLD = 0.18;
const MIN_SHARED_TITLE_TOKENS = 3;
const MIN_SHARED_SHINGLES = 15;

export function normalizeContentTokens(value) {
  return String(value ?? "")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .toLowerCase()
    .split(/\s+/u)
    .filter((token) => token && !COMMON_TOKENS.has(token));
}

function sharedCount(left, right) {
  let count = 0;
  for (const value of left) if (right.has(value)) count += 1;
  return count;
}

function shingles(value) {
  const tokens = normalizeContentTokens(value);
  const result = new Set();
  for (let index = 0; index + 5 <= tokens.length; index += 1) {
    result.add(tokens.slice(index, index + 5).join(" "));
  }
  return result;
}

function normalizedHeadings(headings) {
  return new Set(
    headings
      .map((heading) => normalizeContentTokens(heading).join(" "))
      .filter((heading) => heading && !BOILERPLATE_H2_HEADINGS.has(heading)),
  );
}

export function contentSimilarity(left, right) {
  const leftTitle = new Set(normalizeContentTokens(left.title));
  const rightTitle = new Set(normalizeContentTokens(right.title));
  const sharedTitleTokens = sharedCount(leftTitle, rightTitle);
  const titleUnionSize = new Set([...leftTitle, ...rightTitle]).size;
  const leftHeadings = normalizedHeadings(left.headings);
  const rightHeadings = normalizedHeadings(right.headings);
  const leftShingles = shingles(left.body);
  const rightShingles = shingles(right.body);
  const sharedShingles = sharedCount(leftShingles, rightShingles);
  const shorterShingleSetSize = Math.min(leftShingles.size, rightShingles.size);

  return {
    titleJaccard: titleUnionSize === 0 ? 0 : sharedTitleTokens / titleUnionSize,
    sharedTitleTokens,
    sharedHeadings: sharedCount(leftHeadings, rightHeadings),
    bodyContainment: shorterShingleSetSize === 0 ? 0 : sharedShingles / shorterShingleSetSize,
    sharedShingles,
  };
}

function overlaps(score) {
  return (
    (score.titleJaccard >= TITLE_THRESHOLD && score.sharedTitleTokens >= MIN_SHARED_TITLE_TOKENS)
    || score.sharedHeadings >= 2
    || (score.bodyContainment >= BODY_CONTAINMENT_THRESHOLD && score.sharedShingles >= MIN_SHARED_SHINGLES)
  );
}

export function verifyContentDistinctness(posts, targetSlugs) {
  const errors = [];
  for (const target of posts.filter((post) => targetSlugs.has(post.slug))) {
    for (const existing of posts) {
      if (existing.slug === target.slug) continue;
      const score = contentSimilarity(target, existing);
      if (overlaps(score)) errors.push(`${target.slug}: ${existing.slug} 콘텐츠가 겹칩니다`);
    }
  }
  return errors;
}

function parseArgs(argv) {
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const options = { contentRoot: path.resolve(scriptDir, "..", "..", "docs", "blog-content") };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--content-root" && argv[index + 1]) options.contentRoot = path.resolve(argv[++index]);
    else throw new Error(`알 수 없는 인자입니다: ${argv[index]}`);
  }
  return options;
}

function markdownFiles(root) {
  const files = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile() && entry.name.endsWith(".md")) files.push(file);
    }
  };
  visit(root);
  return files.sort();
}

function loadPosts(contentRoot) {
  if (!fs.existsSync(contentRoot)) throw new Error(`원고 폴더가 없습니다: ${contentRoot}`);
  const posts = [];
  for (const file of markdownFiles(contentRoot)) {
    const source = fs.readFileSync(file, "utf8");
    const metaMatch = source.match(/<!--\s*blog-meta\s*\n([\s\S]*?)\n-->/);
    if (!metaMatch) continue;
    const meta = JSON.parse(metaMatch[1]);
    if (!meta || typeof meta.slug !== "string" || !meta.slug.trim()) {
      throw new Error(`${path.relative(contentRoot, file)}: slug가 없습니다`);
    }
    const body = source.split(/<!--\s*blog-body\s*-->/, 2)[1] ?? "";
    posts.push({
      slug: meta.slug,
      filename: path.relative(contentRoot, file),
      title: source.match(/^#\s+(.+)$/m)?.[1].trim() ?? "",
      body,
      headings: [...body.matchAll(/^##\s+(.+)$/gm)].map((match) => match[1].trim()),
    });
  }
  return posts;
}

function formatScore(score) {
  return `제목 ${score.titleJaccard.toFixed(2)} (${score.sharedTitleTokens}개), H2 ${score.sharedHeadings}개, 본문 ${score.bodyContainment.toFixed(2)} (${score.sharedShingles}개)`;
}

async function main() {
  try {
    const posts = loadPosts(parseArgs(process.argv.slice(2)).contentRoot);
    const pairs = [];
    for (let leftIndex = 0; leftIndex < posts.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < posts.length; rightIndex += 1) {
        const left = posts[leftIndex];
        const right = posts[rightIndex];
        const score = contentSimilarity(right, left);
        if (overlaps(score)) pairs.push({ left, right, score });
      }
    }
    if (pairs.length > 0) {
      console.error(`콘텐츠 중복 검사 실패 (${pairs.length}건)`);
      for (const { left, right, score } of pairs) {
        console.error(`- ${right.slug}: ${left.slug} 콘텐츠가 겹칩니다 (${formatScore(score)})`);
      }
      process.exitCode = 1;
      return;
    }
    console.log(`콘텐츠 중복 검사 통과: 원고 ${posts.length}편`);
  } catch (error) {
    console.error(`콘텐츠 중복 검사 실패\n- ${error.message}`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
