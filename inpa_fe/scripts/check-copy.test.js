const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { scanCopy } = require("./check-copy");

function scanCustomerComparison(source) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "inpa-copy-"));
  const file = path.join(root, "app/customer/[id]/page.tsx");
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, source);
    return scanCopy(root).violations;
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

function scanCopyLibrary(source) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "inpa-copy-"));
  const file = path.join(root, "lib/copy-library.ts");
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, source);
    return scanCopy(root).violations;
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

test("blocks retired rendered comparison labels", () => {
  for (const label of [
    "증권 A",
    "증권 B",
    "비교 묶음 A",
    "비교 묶음 B",
  ]) {
    const violations = scanCustomerComparison(
      `export default function Page(){return <div>${label}</div>}`,
    );
    assert.equal(violations.length, 1);
  }
});

test("allows comments and compatibility keys", () => {
  const violations = scanCustomerComparison(`
    // 증권 A는 과거 화면 용어다.
    const payload = { side_a_ids: [1], side_b_ids: [2] };
    export default function Page(){return <div>{payload.current}</div>}
  `);
  assert.equal(violations.length, 0);
});

test("blocks passive, unsupported, and fabricated talk-template claims", () => {
  for (const phrase of [
    "마음에 걸리는",
    "편하실 때",
    "천천히 생각",
    "결정은 고객님 몫",
    "보험료를 아낀 분도 많아요",
    "받을 수 있는 돈",
    "어느 쪽이 유리",
    "예전 상품엔 약한",
    "굳이 바꿀 필요 없어",
    "뭘 권하려는 건 아니고",
    "무료",
    "객관적으로",
    "정확히 봐",
    "보장 공백",
    "10분 안에",
    "어제 인사드린",
    "링크 전달",
  ]) {
    const violations = scanCopyLibrary(
      `export const body = ${JSON.stringify(phrase)};`,
    );
    assert.equal(violations.length, 1, phrase);
  }
});

test("blocks hard-coded phone and opt-out numbers in talk templates", () => {
  for (const phone of ["010-1234-5678", "080-123-4567", "02-1234-5678"]) {
    const violations = scanCopyLibrary(
      `export const body = ${JSON.stringify(phone)};`,
    );
    assert.equal(violations.length, 1, phone);
  }
});
