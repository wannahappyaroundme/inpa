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
