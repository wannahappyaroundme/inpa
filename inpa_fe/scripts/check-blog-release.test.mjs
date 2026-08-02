import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { parseWebpDimensions } from "./check-blog-release.mjs";

const SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), "check-blog-release.mjs");

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
  const slugs = Array.from({ length: 20 }, (_, index) => `검증-글-${String(index + 1).padStart(2, "0")}`);
  for (const [index, slug] of slugs.entries()) {
    const dir = path.join(assetsRoot, slug);
    fs.mkdirSync(dir, { recursive: true });
    const cover = makeWebp(1600, 900, index + 1);
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

    let body = "본문입니다.";
    if (index === 0) {
      const inline = makeWebp(1200, 800, 31);
      const digest = crypto.createHash("sha256").update(inline).digest("hex").slice(0, 8);
      const filename = `diagram-${digest}.webp`;
      fs.writeFileSync(path.join(dir, filename), inline);
      const inlinePath = `/blog-assets/${slug}/${filename}`;
      manifest.push({
        path: inlinePath,
        role: "diagram",
        source_type: "original-diagram",
        license: "project-owned",
        created_at: "2026-08-03",
        used_by: [slug],
        pii_reviewed: true,
        rights_reviewed: true,
        width: 1200,
        height: 800,
        alt: "상담 준비 순서를 항목별로 차례대로 보여주는 설명 도식",
        caption: "상담 준비 순서",
      });
      body = `![상담 준비 순서를 항목별로 차례대로 보여주는 설명 도식](${inlinePath})`;
    }
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
      sources: [],
    };
    fs.writeFileSync(
      path.join(contentRoot, `${String(index + 1).padStart(2, "0")}-${slug}.md`),
      `<!-- blog-meta\n${JSON.stringify(meta)}\n-->\n# ${slug}\n\n<!-- blog-body -->\n\n${body}\n`,
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

test("accepts a complete 20-post fixture with Unicode paths", () => {
  const fixture = createFixture();
  try {
    const result = run(fixture);
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  } finally {
    fs.rmSync(fixture.root, { recursive: true, force: true });
  }
});

test("reads VP8X, VP8L, and VP8 dimensions without external binaries", () => {
  assert.deepEqual(parseWebpDimensions(makeWebp(1600, 900)), { width: 1600, height: 900 });
  assert.deepEqual(parseWebpDimensions(makeVp8lWebp(1234, 777)), { width: 1234, height: 777 });
  assert.deepEqual(parseWebpDimensions(makeVp8Webp(640, 360)), { width: 640, height: 360 });
});

test("fails for a manifest file that is missing on disk", () => {
  expectFailure(({ assetsRoot, slugs }) => fs.unlinkSync(path.join(assetsRoot, slugs[0], "cover.webp")), /파일이 없습니다/);
});

test("fails for an undeclared WebP", () => {
  expectFailure(({ assetsRoot, slugs }) => fs.writeFileSync(path.join(assetsRoot, slugs[0], "extra.webp"), makeWebp(100, 100)), /manifest에 선언되지 않은 WebP/);
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

test("fails for byte-identical covers", () => {
  expectFailure(({ assetsRoot, slugs }) => {
    const first = fs.readFileSync(path.join(assetsRoot, slugs[0], "cover.webp"));
    fs.writeFileSync(path.join(assetsRoot, slugs[1], "cover.webp"), first);
  }, /대표 이미지가 바이트 단위로 중복/);
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
