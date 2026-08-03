import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import { parseWebpDimensions } from "./check-blog-release.mjs";

const SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), "check-blog-release.mjs");
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
  Array.from({ length: 20 }, (_, index) => makeValidRaster(1600, 900, index + 101)),
);
const VALID_FIXTURE_INLINE = await makeValidRaster(1200, 800, 999);

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
  const slugs = Array.from({ length: 20 }, (_, index) => `검증-글-${String(index + 1).padStart(2, "0")}`);
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

    let body = "본문입니다.";
    if (index === 0) {
      const inline = VALID_FIXTURE_INLINE;
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
    const shared = inlineEntry(fixture);
    shared.used_by.push(fixture.slugs[1]);
    const secondDoc = path.join(fixture.contentRoot, `02-${fixture.slugs[1]}.md`);
    fs.writeFileSync(
      secondDoc,
      fs.readFileSync(secondDoc, "utf8").replace(
        "본문입니다.",
        `![상담 준비 순서를 항목별로 차례대로 보여주는 설명 도식](${shared.path})`,
      ),
    );
    writeJson(path.join(fixture.assetsRoot, "manifest.json"), fixture.manifest);
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
