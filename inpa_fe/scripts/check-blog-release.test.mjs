import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import {
  contentSimilarity,
  normalizeContentTokens,
  verifyContentDistinctness,
} from "./blog-content-distinctness.mjs";
import {
  PROTECTED_EXISTING_ASSET_PATHS,
  parseWebpDimensions,
  verifyNewPostProductCaptures,
  verifyProtectedExistingAssetDigests,
} from "./check-blog-release.mjs";

const SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), "check-blog-release.mjs");
const DISTINCTNESS_SCRIPT = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "blog-content-distinctness.mjs",
);
const VISUAL_FIXTURE_SVG = Buffer.from(`
  <svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">
    <defs><linearGradient id="g"><stop stop-color="#3157d5"/><stop offset="1" stop-color="#f3f5f9"/></linearGradient></defs>
    <rect width="1600" height="900" fill="url(#g)"/>
    <circle cx="420" cy="450" r="220" fill="#fff" opacity=".8"/>
    <rect x="790" y="240" width="510" height="420" rx="52" fill="#172342"/>
  </svg>
`);
const VISUAL_COVER_A = await sharp(VISUAL_FIXTURE_SVG).webp({ quality: 72 }).toBuffer();
const VISUAL_COVER_B = await sharp(VISUAL_FIXTURE_SVG).webp({ quality: 94 }).toBuffer();

function post({ slug, title = "", body = "", headings = [] }) {
  return { slug, filename: `${slug}.md`, title, body, headings };
}

function tokenSequence(prefix, count) {
  return Array.from({ length: count }, (_, index) => `${prefix}${index + 1}`).join(" ");
}

test("new post copied from a recent post is blocked", () => {
  const copiedBody = `## 월요일에는 빈칸부터 찾습니다\n\n${tokenSequence("copied", 24)}`;
  const recent = post({
    slug: "보험설계사-주간-계획표-고객-단계별-다음-행동",
    title: "보험설계사 주간 계획표, 고객 단계별로 다음 행동 정하기",
    body: copiedBody,
  });
  const copied = post({
    slug: "보험설계사-새로운-영업-계획",
    title: "보험설계사 영업 계획표, 고객 단계별 다음 행동 정하기",
    body: copiedBody,
  });

  const errors = verifyContentDistinctness([recent, copied], new Set([copied.slug]));

  assert.ok(errors.some((error) => error.includes("콘텐츠가 겹칩니다")));
});

test("approved common words alone do not block distinct posts", () => {
  const first = post({
    slug: "첫-글",
    title: "보험설계사 보험 고객 확인 방법 정리 인파 첫 주제",
    body: "## 첫 번째 흐름\n\n서로 다른 내용을 설명합니다.",
    headings: ["첫 번째 흐름"],
  });
  const second = post({
    slug: "둘-글",
    title: "보험설계사 보험 고객 확인 방법 정리 인파 둘 주제",
    body: "## 두 번째 흐름\n\n전혀 다른 소재를 다룹니다.",
    headings: ["두 번째 흐름"],
  });

  assert.deepEqual(normalizeContentTokens(first.title), ["첫", "주제"]);
  assert.deepEqual(verifyContentDistinctness([first, second], new Set([second.slug])), []);
});

test("title similarity at the exact threshold blocks a new post", () => {
  const shared = tokenSequence("shared", 18);
  const recent = post({ slug: "최근", title: `${shared} left1 left2 left3` });
  const target = post({ slug: "대상", title: `${shared} right1 right2 right3 right4` });

  const score = contentSimilarity(target, recent);

  assert.equal(score.titleJaccard, 0.72);
  assert.equal(score.sharedTitleTokens, 18);
  assert.ok(verifyContentDistinctness([recent, target], new Set([target.slug])).length > 0);
});

test("fewer than three shared title tokens do not block a new post", () => {
  const recent = post({ slug: "최근", title: "shared1 shared2" });
  const target = post({ slug: "대상", title: "shared1 shared2" });

  const score = contentSimilarity(target, recent);

  assert.equal(score.titleJaccard, 1);
  assert.equal(score.sharedTitleTokens, 2);
  assert.deepEqual(verifyContentDistinctness([recent, target], new Set([target.slug])), []);
});

test("one shared normalized H2 does not block a new post", () => {
  const recent = post({ slug: "최근", title: "서로 다른 제목 하나", headings: ["같은 소제목"] });
  const target = post({ slug: "대상", title: "완전히 다른 제목 둘", headings: ["같은 소제목"] });

  assert.equal(contentSimilarity(target, recent).sharedHeadings, 1);
  assert.deepEqual(verifyContentDistinctness([recent, target], new Set([target.slug])), []);
});

test("two boilerplate H2 headings do not block a new post", () => {
  const recent = post({
    slug: "최근",
    title: "서로 다른 제목 하나",
    headings: ["흔히 놓치는 점", "저장용 체크리스트"],
  });
  const target = post({
    slug: "대상",
    title: "완전히 다른 제목 둘",
    headings: ["흔히 놓치는 점", "저장용 체크리스트"],
  });

  assert.equal(contentSimilarity(target, recent).sharedHeadings, 0);
  assert.deepEqual(verifyContentDistinctness([recent, target], new Set([target.slug])), []);
});

test("two shared substantive H2 headings block a new post", () => {
  const recent = post({
    slug: "최근",
    title: "서로 다른 제목 하나",
    headings: ["상담 기록을 남기는 순서", "다음 연락을 정하는 기준"],
  });
  const target = post({
    slug: "대상",
    title: "완전히 다른 제목 둘",
    headings: ["상담 기록을 남기는 순서", "다음 연락을 정하는 기준"],
  });

  assert.equal(contentSimilarity(target, recent).sharedHeadings, 2);
  assert.ok(verifyContentDistinctness([recent, target], new Set([target.slug])).length > 0);
});

test("fourteen shared five-token shingles do not block a new post", () => {
  const body = tokenSequence("body", 18);
  const recent = post({ slug: "최근", title: "첫 번째 제목", body });
  const target = post({ slug: "대상", title: "두 번째 제목", body });

  const score = contentSimilarity(target, recent);

  assert.equal(score.sharedShingles, 14);
  assert.equal(score.bodyContainment, 1);
  assert.deepEqual(verifyContentDistinctness([recent, target], new Set([target.slug])), []);
});

test("duplicated long content blocks a new post", () => {
  const body = tokenSequence("body", 24);
  const recent = post({ slug: "최근", title: "첫 번째 제목", body });
  const target = post({ slug: "대상", title: "두 번째 제목", body });

  const score = contentSimilarity(target, recent);

  assert.equal(score.sharedShingles, 20);
  assert.equal(score.bodyContainment, 1);
  assert.ok(verifyContentDistinctness([recent, target], new Set([target.slug])).length > 0);
});

test("body containment uses the shorter shingle set for a longer copied target in either order", () => {
  const recentBody = tokenSequence("shared", 24);
  const targetBody = `${recentBody} ${tokenSequence("tail", 120)}`;
  const recent = post({ slug: "짧은-기존-글", title: "첫 번째 제목", body: recentBody });
  const target = post({ slug: "긴-신규-글", title: "두 번째 제목", body: targetBody });

  const targetFirst = contentSimilarity(target, recent);
  const recentFirst = contentSimilarity(recent, target);

  assert.equal(targetFirst.sharedShingles, 20);
  assert.equal(targetFirst.bodyContainment, 1);
  assert.equal(recentFirst.bodyContainment, 1);
  assert.deepEqual(verifyContentDistinctness([recent, target], new Set([target.slug])), [
    "긴-신규-글: 짧은-기존-글 콘텐츠가 겹칩니다",
  ]);
});

test("body containment is zero when either shingle set is empty", () => {
  const empty = post({ slug: "빈-글", title: "빈 제목", body: "단어가 넷 이하" });
  const populated = post({ slug: "긴-글", title: "긴 제목", body: tokenSequence("body", 9) });

  assert.equal(contentSimilarity(empty, empty).bodyContainment, 0);
  assert.equal(contentSimilarity(empty, populated).bodyContainment, 0);
  assert.equal(contentSimilarity(populated, empty).bodyContainment, 0);
});

test("standalone distinctness CLI blocks a longer copied post regardless of file order", (t) => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "inpa-blog-distinctness-"));
  t.after(() => fs.rmSync(tempRoot, { recursive: true, force: true }));
  const recentBody = tokenSequence("shared", 24);
  const targetBody = `${recentBody} ${tokenSequence("tail", 120)}`;
  const cases = [
    { name: "longer-file-sorts-last", recentFile: "a-recent.md", targetFile: "z-target.md" },
    { name: "longer-file-sorts-first", recentFile: "z-recent.md", targetFile: "a-target.md" },
  ];

  for (const fixture of cases) {
    const contentRoot = path.join(tempRoot, fixture.name);
    fs.mkdirSync(contentRoot, { recursive: true });
    const writePost = (filename, slug, title, body) => {
      fs.writeFileSync(
        path.join(contentRoot, filename),
        `<!-- blog-meta\n${JSON.stringify({ slug })}\n-->\n# ${title}\n\n<!-- blog-body -->\n${body}\n`,
      );
    };
    writePost(fixture.recentFile, "짧은-원고", "서로 다른 첫 제목", recentBody);
    writePost(fixture.targetFile, "긴-복제-원고", "완전히 다른 둘 제목", targetBody);

    const result = spawnSync(
      process.execPath,
      [DISTINCTNESS_SCRIPT, "--content-root", contentRoot],
      { encoding: "utf8" },
    );

    assert.equal(
      result.status,
      1,
      `${fixture.name}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
    );
    assert.match(result.stderr, /콘텐츠 중복 검사 실패/);
    assert.match(result.stderr, /짧은-원고/);
    assert.match(result.stderr, /긴-복제-원고/);
  }
});

async function makeValidRaster(width, height, seed) {
  const pixels = Buffer.alloc(9 * 8);
  let state = seed * 0x9e3779b1;
  for (let index = 0; index < pixels.length; index += 1) {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    pixels[index] = state & 0xff;
  }
  return sharp(pixels, { raw: { width: 9, height: 8, channels: 1 } })
    .resize(width, height, { kernel: "nearest" })
    .webp({ lossless: true })
    .toBuffer();
}

const VALID_FIXTURE_COVERS = await Promise.all(
  Array.from({ length: 31 }, (_, index) => makeValidRaster(1600, 900, index + 101)),
);
const VALID_FIXTURE_INLINE = await Promise.all(
  Array.from({ length: 48 }, (_, index) => makeValidRaster(1600, 900, index + 1001)),
);

const NEW_RELEASE_SLUGS = [
  "보험설계사-고객관리-프로그램-선택-기준",
  "보험설계사-보장분석-프로그램-확인-항목",
  "보험설계사-고객-자료-파일-정리",
  "보험설계사-휴면-고객-다시-연락",
  "보험설계사-상담-예약-링크",
  "보장분석-결과-고객-공유",
];

const RECENT_PRIOR_RELEASE_SLUGS = [
  "보험설계사-주간-계획표-고객-단계별-다음-행동",
  "보험설계사-소개-카드-고객-확인사항",
  "보험설계사-월말-복기-영업-숫자",
  "보험설계사-고객-연간-일정-관리법",
  "보험설계사-팀장-일대일-질문",
];

function readRealManifest() {
  return JSON.parse(fs.readFileSync(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../public/blog-assets/manifest.json"),
    "utf8",
  ));
}

test("booking request flow caption matches the five numbered stages", () => {
  const record = readRealManifest().find((entry) => (
    entry.path.endsWith("/booking-request-flow-1ea92e41.webp")
  ));

  assert.equal(record?.caption, "업무시간 설정과 고객 요청을 거쳐 상담을 확정하는 다섯 단계");
});

test("protected prior-asset lock exactly covers all 61 assets from posts 1 through 25", () => {
  const manifest = readRealManifest();
  const newSlugs = new Set(NEW_RELEASE_SLUGS);
  const expectedPriorPaths = manifest
    .filter((entry) => !entry.used_by.some((slug) => newSlugs.has(slug)))
    .map((entry) => entry.path)
    .sort();

  assert.equal(expectedPriorPaths.length, 61);
  assert.equal(Object.isFrozen(PROTECTED_EXISTING_ASSET_PATHS), true);
  assert.deepEqual(PROTECTED_EXISTING_ASSET_PATHS, expectedPriorPaths);

  for (const slug of RECENT_PRIOR_RELEASE_SLUGS) {
    const recentPaths = manifest
      .filter((entry) => entry.used_by.includes(slug))
      .map((entry) => entry.path);
    assert.equal(recentPaths.length, 3, `${slug} 보호 대상은 3개여야 합니다`);
    for (const assetPath of recentPaths) {
      assert.ok(
        PROTECTED_EXISTING_ASSET_PATHS.includes(assetPath),
        `${assetPath} 보호 잠금이 빠졌습니다`,
      );
    }
  }
});

function makeWebp(width, height, seed = 0, padding = 0) {
  const payload = Buffer.alloc(10);
  payload[0] = seed;
  payload.writeUIntLE(width - 1, 4, 3);
  payload.writeUIntLE(height - 1, 7, 3);
  const chunk = Buffer.concat([Buffer.from("VP8X"), sizeLE(payload.length), payload]);
  const declaredSize = 4 + chunk.length;
  return Buffer.concat([
    Buffer.from("RIFF"),
    sizeLE(declaredSize),
    Buffer.from("WEBP"),
    chunk,
    Buffer.alloc(padding, seed),
  ]);
}

function makeChunkWebp(kind, payload) {
  const padded = payload.length % 2 ? Buffer.concat([payload, Buffer.from([0])]) : payload;
  const chunk = Buffer.concat([Buffer.from(kind), sizeLE(payload.length), padded]);
  return Buffer.concat([Buffer.from("RIFF"), sizeLE(4 + chunk.length), Buffer.from("WEBP"), chunk]);
}

function appendWebpChunk(buffer, kind, payload) {
  const padded = payload.length % 2 ? Buffer.concat([payload, Buffer.from([0])]) : payload;
  const chunk = Buffer.concat([Buffer.from(kind), sizeLE(payload.length), padded]);
  const result = Buffer.concat([buffer, chunk]);
  result.writeUInt32LE(result.length - 8, 4);
  return result;
}

function makeVp8lWebp(width, height) {
  const w = width - 1;
  const h = height - 1;
  return makeChunkWebp("VP8L", Buffer.from([
    0x2f,
    w & 0xff,
    ((w >> 8) & 0x3f) | ((h & 0x03) << 6),
    (h >> 2) & 0xff,
    (h >> 10) & 0x0f,
  ]));
}

function makeVp8Webp(width, height) {
  const payload = Buffer.alloc(10);
  payload.set([0x9d, 0x01, 0x2a], 3);
  payload.writeUInt16LE(width, 6);
  payload.writeUInt16LE(height, 8);
  return makeChunkWebp("VP8 ", payload);
}

function sizeLE(value) {
  const bytes = Buffer.alloc(4);
  bytes.writeUInt32LE(value);
  return bytes;
}

function writeJson(file, value) {
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`);
}

function inlineEntry(fixture) {
  return fixture.manifest.find((entry) => entry.role !== "cover");
}

function createFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "inpa-blog-lint-"));
  const frontendRoot = path.join(root, "inpa_fe");
  const assetsRoot = path.join(frontendRoot, "public", "blog-assets");
  const contentRoot = path.join(root, "docs", "blog-content");
  fs.mkdirSync(assetsRoot, { recursive: true });
  fs.mkdirSync(contentRoot, { recursive: true });

  const manifest = [];
  const slugs = [
    ...Array.from({ length: 25 }, (_, index) => `검증-글-${String(index + 1).padStart(2, "0")}`),
    ...NEW_RELEASE_SLUGS,
  ];
  let inlineIndex = 0;
  for (const [index, slug] of slugs.entries()) {
    const dir = path.join(assetsRoot, slug);
    fs.mkdirSync(dir, { recursive: true });
    const cover = VALID_FIXTURE_COVERS[index];
    fs.writeFileSync(path.join(dir, "cover.webp"), cover);
    const coverPath = `/blog-assets/${slug}/cover.webp`;
    manifest.push({
      path: coverPath,
      role: "cover",
      source_type: "original-diagram",
      license: "project-owned",
      created_at: "2026-08-03",
      used_by: [slug],
      pii_reviewed: true,
      rights_reviewed: true,
      width: 1600,
      height: 900,
      alt: "",
      caption: `${slug} 글의 장식용 대표 이미지`,
    });

    const inlineCount = index >= 25 ? 2 : index < 11 ? 2 : 1;
    const bodyImages = [];
    for (let imageIndex = 0; imageIndex < inlineCount; imageIndex += 1) {
      const inline = VALID_FIXTURE_INLINE[inlineIndex++];
      const digest = crypto.createHash("sha256").update(inline).digest("hex").slice(0, 8);
      const isNewPost = index >= 25;
      const isProductCapture = isNewPost && imageIndex === 1;
      const filename = `${isProductCapture ? "product-screen" : "diagram"}-${digest}.webp`;
      fs.writeFileSync(path.join(dir, filename), inline);
      const inlinePath = `/blog-assets/${slug}/${filename}`;
      manifest.push({
        path: inlinePath,
        role: isProductCapture ? "product-screen" : "diagram",
        source_type: isProductCapture ? "product-capture" : "original-diagram",
        license: "project-owned",
        created_at: isNewPost ? "2026-08-10" : "2026-08-03",
        used_by: [slug],
        pii_reviewed: true,
        rights_reviewed: true,
        width: 1600,
        height: 900,
        alt: `검증화면${index + 1}항목${imageIndex + 1}가나다라마바사아자차카타파하정보그림`,
        caption: isProductCapture ? "촬영용 합성 데이터 제품 화면" : "상담 준비 순서",
      });
      bodyImages.push(`![${manifest.at(-1).alt}](${inlinePath})`);
    }
    const body = bodyImages.length ? bodyImages.join("\n\n") : "본문입니다.";
    const meta = {
      slug,
      category: "sales",
      excerpt: "검증용 원고",
      tags: ["검증"],
      seo_title: "검증용 제목",
      seo_description: "검증용 설명",
      cover_asset_path: coverPath,
      is_published: true,
      review_gate: "none",
      legal_review: null,
      publication_plan_at: "2026-08-10T10:20:00+09:00",
      sources: [],
    };
    fs.writeFileSync(
      path.join(contentRoot, `${String(index + 1).padStart(2, "0")}-${slug}.md`),
      `<!-- blog-meta\n${JSON.stringify(meta)}\n-->\n# 검증제목${index + 1}\n\n<!-- blog-body -->\n\n${body}\n`,
    );
  }
  writeJson(path.join(assetsRoot, "manifest.json"), manifest);
  return { root, frontendRoot, assetsRoot, contentRoot, manifest, slugs };
}

function run(fixture) {
  return spawnSync(
    process.execPath,
    [SCRIPT, "--frontend-root", fixture.frontendRoot, "--content-root", fixture.contentRoot],
    { encoding: "utf8" },
  );
}

function expectFailure(mutate, expected) {
  const fixture = createFixture();
  try {
    mutate(fixture);
    const result = run(fixture);
    assert.notEqual(result.status, 0, result.stdout);
    assert.match(`${result.stdout}\n${result.stderr}`, expected);
  } finally {
    fs.rmSync(fixture.root, { recursive: true, force: true });
  }
}

test("accepts exactly 31 posts, 31 covers, and 79 assets", () => {
  const fixture = createFixture();
  try {
    const result = run(fixture);
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    assert.match(result.stdout, /원고 31편, 대표 이미지 31개, 전체 자산 79개/);
  } finally {
    fs.rmSync(fixture.root, { recursive: true, force: true });
  }
});

test("fails when a new post does not have exactly one original diagram and one product capture", () => {
  for (const sourceType of ["generated-object", "original-diagram"]) {
    expectFailure((fixture) => {
      const slug = NEW_RELEASE_SLUGS[0];
      const entry = fixture.manifest.find((record) => (
        record.used_by.includes(slug)
        && (sourceType === "generated-object" ? record.role === "diagram" : record.role === "product-screen")
      ));
      entry.source_type = sourceType;
      writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
    }, /신규 글에는 original-diagram 도식과 product-capture 제품 화면이 각각 정확히 1개 필요합니다/);
  }
});

test("fails when any new inline asset copies bytes from another asset", () => {
  expectFailure((fixture) => {
    const source = fixture.manifest.find((record) => (
      record.role === "diagram" && record.used_by.includes(NEW_RELEASE_SLUGS[0])
    ));
    const target = fixture.manifest.find((record) => (
      record.role === "product-screen" && record.used_by.includes(NEW_RELEASE_SLUGS[1])
    ));
    const sourceFile = path.join(fixture.frontendRoot, "public", ...source.path.slice(1).split("/"));
    const targetFile = path.join(fixture.frontendRoot, "public", ...target.path.slice(1).split("/"));
    const copied = fs.readFileSync(sourceFile);
    const digest = crypto.createHash("sha256").update(copied).digest("hex").slice(0, 8);
    const copiedName = `product-screen-${digest}.webp`;
    const copiedPath = `/blog-assets/${NEW_RELEASE_SLUGS[1]}/${copiedName}`;
    fs.unlinkSync(targetFile);
    fs.writeFileSync(path.join(path.dirname(targetFile), copiedName), copied);
    const oldPath = target.path;
    target.path = copiedPath;
    const doc = path.join(fixture.contentRoot, `27-${NEW_RELEASE_SLUGS[1]}.md`);
    fs.writeFileSync(doc, fs.readFileSync(doc, "utf8").replace(oldPath, copiedPath));
    writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
  }, /신규 자산이 다른 자산과 바이트 단위로 중복됩니다/);
});

test("fails unless the manifest contains exactly 79 assets", () => {
  expectFailure((fixture) => {
    const removed = fixture.manifest.pop();
    const file = path.join(fixture.frontendRoot, "public", ...removed.path.slice(1).split("/"));
    fs.unlinkSync(file);
    const doc = path.join(fixture.contentRoot, `31-${NEW_RELEASE_SLUGS.at(-1)}.md`);
    const source = fs.readFileSync(doc, "utf8");
    fs.writeFileSync(doc, source.replace(new RegExp(`\\n\\n!\\[[^\\]]+\\]\\(${removed.path.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")}\\)`), ""));
    writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
  }, /전체 자산 manifest 항목은 정확히 79개여야 합니다/);
});

test("fails when publication_plan_at is missing or has no KST offset", () => {
  for (const invalid of [undefined, "2026-08-10T10:20:00", "2026-08-10T01:20:00+00:00"]) {
    expectFailure((fixture) => {
      const doc = path.join(fixture.contentRoot, `01-${fixture.slugs[0]}.md`);
      const source = fs.readFileSync(doc, "utf8");
      const match = source.match(/<!--\s*blog-meta\s*\n([\s\S]*?)\n-->/);
      const meta = JSON.parse(match[1]);
      if (invalid === undefined) delete meta.publication_plan_at;
      else meta.publication_plan_at = invalid;
      fs.writeFileSync(doc, source.replace(match[1], JSON.stringify(meta)));
    }, /publication_plan_at/);
  }
});

test("reads VP8X, VP8L, and VP8 dimensions without external binaries", () => {
  assert.deepEqual(parseWebpDimensions(makeWebp(1600, 900)), { width: 1600, height: 900 });
  assert.deepEqual(parseWebpDimensions(makeVp8lWebp(1234, 777)), { width: 1234, height: 777 });
  assert.deepEqual(parseWebpDimensions(makeVp8Webp(640, 360)), { width: 640, height: 360 });
});

test("fails when an existing post asset changes from the approved v1 release", () => {
  const protectedCover = "/blog-assets/보험-가입-전-확인사항/cover.webp";
  const protectedInline = "/blog-assets/보험-가입-전-확인사항/five-questions-2ed62021.webp";
  const errors = [];

  verifyProtectedExistingAssetDigests({
    slugs: new Set(["보험-가입-전-확인사항"]),
    digestByPath: new Map([
      [protectedCover, "changed"],
      [protectedInline, "2ed6202123dad2ccf95520bc0ef7507932cf0a36cdde15d0bfc049320e59c2bf"],
    ]),
    errors,
  });

  assert.deepEqual(errors, [`${protectedCover}: 기존 25편 자산은 승인된 해시를 보존해야 합니다`]);
});

test("fails when a new post uses a drawn mockup instead of a product capture", () => {
  const errors = [];
  const screenPath = "/blog-assets/보험설계사-주간-계획표-고객-단계별-다음-행동/screen-deadbeef.webp";

  verifyNewPostProductCaptures({
    posts: [{
      filename: "21-sales.md",
      meta: { slug: "보험설계사-주간-계획표-고객-단계별-다음-행동" },
      images: [screenPath],
    }],
    byPath: new Map([[screenPath, { role: "product-screen", source_type: "original-diagram" }]]),
    errors,
  });

  assert.deepEqual(errors, ["21-sales.md: 실제 인파 제품 화면(product-capture)이 정확히 1개 필요합니다"]);
});

test("fails for a manifest file that is missing on disk", () => {
  expectFailure(({ assetsRoot, slugs }) => fs.unlinkSync(path.join(assetsRoot, slugs[0], "cover.webp")), /파일이 없습니다/);
});

test("fails for an undeclared WebP", () => {
  expectFailure(({ assetsRoot, slugs }) => fs.writeFileSync(path.join(assetsRoot, slugs[0], "extra.webp"), makeWebp(100, 100)), /manifest에 선언되지 않은 파일/);
});

test("fails for an undeclared non-WebP file in the public asset folder", () => {
  expectFailure(({ assetsRoot, slugs }) => {
    fs.writeFileSync(path.join(assetsRoot, slugs[0], "cover-source.svg"), "<svg/>");
  }, /manifest에 선언되지 않은 파일/);
});

test("fails for a header-only WebP without decodable raster payload", () => {
  expectFailure(({ assetsRoot, slugs }) => {
    fs.writeFileSync(path.join(assetsRoot, slugs[0], "cover.webp"), makeWebp(1600, 900, 1));
  }, /실제 이미지 데이터/);
});

test("fails for external and traversal asset paths", () => {
  for (const invalid of ["https://example.com/image.webp", "/blog-assets/../secret.webp"]) {
    expectFailure((fixture) => {
      inlineEntry(fixture).path = invalid;
      writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
    }, /안전한 로컬 경로/);
  }
});

test("fails for external and traversal image references in Markdown", () => {
  for (const invalid of ["https://example.com/image.webp", "/blog-assets/../secret.webp"]) {
    expectFailure((fixture) => {
      const entry = inlineEntry(fixture);
      const doc = path.join(fixture.contentRoot, `01-${fixture.slugs[0]}.md`);
      fs.writeFileSync(doc, fs.readFileSync(doc, "utf8").replace(entry.path, invalid));
    }, /본문 이미지는 .*안전한 로컬 경로/);
  }
});

test("fails for external shortcut and collapsed image references in Markdown", () => {
  for (const reference of [
    "![외부 이미지]\n\n[외부 이미지]: https://example.com/shortcut.webp",
    "![외부 이미지][]\n\n[외부 이미지]: https://example.com/collapsed.webp",
  ]) {
    expectFailure((fixture) => {
      const entry = inlineEntry(fixture);
      const doc = path.join(fixture.contentRoot, `01-${fixture.slugs[0]}.md`);
      fs.writeFileSync(doc, fs.readFileSync(doc, "utf8").replace(
        /!\[[^\]]+\]\([^\)]+\)/,
        reference,
      ));
    }, /본문 이미지는 .*안전한 로컬 경로/);
  }
});

test("fails for byte-identical covers", () => {
  expectFailure(({ assetsRoot, slugs }) => {
    const first = fs.readFileSync(path.join(assetsRoot, slugs[0], "cover.webp"));
    fs.writeFileSync(path.join(assetsRoot, slugs[1], "cover.webp"), first);
  }, /대표 이미지가 바이트 단위로 중복/);
});

test("fails for visually identical covers even when WebP bytes differ", () => {
  assert.notDeepEqual(VISUAL_COVER_A, VISUAL_COVER_B);
  expectFailure(({ assetsRoot, slugs }) => {
    fs.writeFileSync(path.join(assetsRoot, slugs[0], "cover.webp"), VISUAL_COVER_A);
    fs.writeFileSync(path.join(assetsRoot, slugs[1], "cover.webp"), VISUAL_COVER_B);
  }, /대표 이미지가 시각적으로 중복/);
});

test("fails when a WebP contains EXIF, XMP, or ICC metadata chunks", () => {
  for (const kind of ["EXIF", "XMP ", "ICCP"]) {
    expectFailure(({ assetsRoot, slugs }) => {
      const file = path.join(assetsRoot, slugs[0], "cover.webp");
      fs.writeFileSync(file, appendWebpChunk(fs.readFileSync(file), kind, Buffer.from("private-metadata")));
    }, /EXIF, XMP, ICC 메타데이터/);
  }
});

test("fails when a post repeats its cover bytes as an inline image", () => {
  expectFailure((fixture) => {
    const entry = inlineEntry(fixture);
    const coverFile = path.join(fixture.assetsRoot, fixture.slugs[0], "cover.webp");
    const cover = fs.readFileSync(coverFile);
    const digest = crypto.createHash("sha256").update(cover).digest("hex").slice(0, 8);
    const oldPath = entry.path;
    const oldFile = path.join(fixture.frontendRoot, "public", ...oldPath.slice(1).split("/"));
    const filename = `diagram-${digest}.webp`;
    const newPath = `/blog-assets/${fixture.slugs[0]}/${filename}`;
    const newFile = path.join(path.dirname(oldFile), filename);
    fs.unlinkSync(oldFile);
    fs.writeFileSync(newFile, cover);
    entry.path = newPath;
    entry.width = 1600;
    entry.height = 900;
    const doc = path.join(fixture.contentRoot, `01-${fixture.slugs[0]}.md`);
    fs.writeFileSync(doc, fs.readFileSync(doc, "utf8").replace(oldPath, newPath));
    writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
  }, /같은 글의 대표 이미지와 바이트가 같습니다/);
});

test("fails for a cover that is not exactly 1600 by 900", () => {
  expectFailure((fixture) => {
    fs.writeFileSync(path.join(fixture.assetsRoot, fixture.slugs[0], "cover.webp"), makeWebp(1200, 675, 1));
    fixture.manifest[0].width = 1200;
    fixture.manifest[0].height = 675;
    writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
  }, /대표 이미지는 1600×900/);
});

test("fails unless PII and rights reviews are literal true", () => {
  for (const field of ["pii_reviewed", "rights_reviewed"]) {
    expectFailure((fixture) => {
      fixture.manifest[0][field] = false;
      writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
    }, new RegExp(`${field}.*true`));
  }
});

test("fails for missing or mismatched manifest dimensions", () => {
  expectFailure((fixture) => {
    delete fixture.manifest[0].width;
    writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
  }, /width와 height는 양의 정수/);
  expectFailure((fixture) => {
    fixture.manifest[0].width = 1599;
    writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
  }, /manifest 크기.*실제 WebP 크기/);
});

test("fails for a missing or too-short informative-image alt", () => {
  for (const alt of ["", "짧은 설명"]) {
    expectFailure((fixture) => {
      inlineEntry(fixture).alt = alt;
      writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
    }, /정보 이미지 alt는 .*20~60자/);
  }
});

test("fails when cover or inline byte budgets are exceeded", () => {
  expectFailure(({ assetsRoot, slugs }) => {
    fs.writeFileSync(path.join(assetsRoot, slugs[0], "cover.webp"), makeWebp(1600, 900, 1, 200 * 1024));
  }, /대표 이미지 용량은 200KB 이하/);
  expectFailure((fixture) => {
    const entry = inlineEntry(fixture);
    const file = path.join(fixture.frontendRoot, "public", ...entry.path.slice(1).split("/"));
    fs.writeFileSync(file, makeWebp(1200, 800, 31, 180 * 1024));
  }, /본문 이미지 용량은 180KB 이하/);
});

test("fails when the conservative 12-cover list budget is exceeded", () => {
  expectFailure((fixture) => {
    for (let index = 0; index < 12; index += 1) {
      fs.writeFileSync(
        path.join(fixture.assetsRoot, fixture.slugs[index], "cover.webp"),
        makeWebp(1600, 900, index + 1, 110 * 1024),
      );
    }
  }, /목록 대표 이미지 합계/);
});

test("fails when one post's cover and inline assets exceed the detail budget", () => {
  expectFailure((fixture) => {
    const slug = fixture.slugs[0];
    const doc = path.join(fixture.contentRoot, `01-${slug}.md`);
    let source = fs.readFileSync(doc, "utf8");
    for (let index = 0; index < 6; index += 1) {
      const bytes = makeWebp(1200, 800, 80 + index, 160 * 1024);
      const digest = crypto.createHash("sha256").update(bytes).digest("hex").slice(0, 8);
      const filename = `detail-${index}-${digest}.webp`;
      const assetPath = `/blog-assets/${slug}/${filename}`;
      fs.writeFileSync(path.join(fixture.assetsRoot, slug, filename), bytes);
      fixture.manifest.push({
        path: assetPath,
        role: "diagram",
        source_type: "original-diagram",
        license: "project-owned",
        created_at: "2026-08-03",
        used_by: [slug],
        pii_reviewed: true,
        rights_reviewed: true,
        width: 1200,
        height: 800,
        alt: `고객 상담 내용을 단계별로 정리해 보여주는 ${index + 1}번 설명 이미지`,
        caption: `고객 상담 정리 ${index + 1}번`,
      });
      source += `\n\n![고객 상담 내용을 단계별로 정리해 보여주는 ${index + 1}번 설명 이미지](${assetPath})`;
    }
    fs.writeFileSync(doc, source);
    writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
  }, /상세 이미지 합계/);
});

test("fails for non-hash and hash-mismatched inline filenames", () => {
  for (const filename of ["diagram.webp", "diagram-deadbeef.webp"]) {
    expectFailure((fixture) => {
      const entry = inlineEntry(fixture);
      const oldFile = path.join(fixture.frontendRoot, "public", ...entry.path.slice(1).split("/"));
      const newFile = path.join(path.dirname(oldFile), filename);
      fs.renameSync(oldFile, newFile);
      entry.path = `/blog-assets/${fixture.slugs[0]}/${filename}`;
      const doc = path.join(fixture.contentRoot, `01-${fixture.slugs[0]}.md`);
      fs.writeFileSync(doc, fs.readFileSync(doc, "utf8").replace(/diagram-[a-f0-9]{8}\.webp/, filename));
      writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
    }, /본문 이미지 파일명.*SHA-256 앞 8자리/);
  }
});
