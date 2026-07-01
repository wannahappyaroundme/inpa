#!/usr/bin/env node
/**
 * 정직성 카피 가드 (P8c) — 렌더링 문자열의 em-dash(—)를 자동 차단한다.
 *
 * 배경: PM 레드라인 "사용자 문구에 em-dash(—, U+2014) 금지"("AI 티")를 사람 검수에만 맡기면
 *      언젠가 샌다. 소스에서 기계적으로 잡아 CI 게이트로 막는다. ★ 코드 주석은 예외(허용).
 *
 * 규칙은 em-dash 하나만 둔다: 오탐 0(한글 UI에서 —는 언제나 불필요). '안전/심의완료/추천' 같은
 * 단어 기반 규칙은 정당한 언급(부인 문구·규칙 설명)까지 잡는 오탐이 커서 의도적으로 제외했다.
 * 필요하면 RULES 배열에 신중히(오탐 검증 후) 추가하면 된다.
 *
 * 검사 대상: inpa_fe/app + inpa_fe/components 의 .ts/.tsx (렌더 표면).
 * 위반 시 file:line 목록 + exit 1. 통과 시 exit 0.
 *
 * 주석 예외 처리: 블록주석은 공백으로(개행 보존 → 줄번호 유지), 줄주석(//)은 제거하되
 *   URL의 :// 는 보존한 뒤 검사한다(휴리스틱).
 *
 * 실행: npm run lint:copy  (또는 node scripts/check-copy.js)
 */
const fs = require("fs");
const path = require("path");

const ROOTS = ["app", "components"];
const EXT = new Set([".ts", ".tsx"]);

// 렌더 카피에 절대 없어야 하는 표기(주석 제거 후 검사). 추가할 땐 여기만 늘리면 됨(오탐 검증 필수).
const RULES = [
  { name: "em-dash(—)", re: /—/, hint: "—는 금지. 쉼표·마침표·콜론·괄호·한글 조사로 바꾸세요." },
];

/** 주석을 검사 대상에서 제외. 블록주석은 공백치환(줄번호 보존), 줄주석은 제거(://는 보존). */
function stripComments(src) {
  let s = src.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  s = s.replace(/(^|[^:])\/\/[^\n]*/g, "$1");
  return s;
}

function walk(dir, out) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, out);
    else if (EXT.has(path.extname(name))) out.push(p);
  }
}

const base = path.resolve(__dirname, "..");
const files = [];
for (const r of ROOTS) {
  const d = path.join(base, r);
  if (fs.existsSync(d)) walk(d, files);
}

const violations = [];
for (const file of files) {
  const raw = fs.readFileSync(file, "utf8");
  const original = raw.split("\n");
  const scanned = stripComments(raw).split("\n");
  for (let i = 0; i < scanned.length; i++) {
    for (const rule of RULES) {
      if (rule.re.test(scanned[i])) {
        violations.push({ file: path.relative(base, file), line: i + 1, rule, text: (original[i] || "").trim() });
      }
    }
  }
}

if (violations.length) {
  console.error(`\n✗ 정직성 카피 가드: 금지 표기 ${violations.length}건 발견\n`);
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line}  [${v.rule.name}] → ${v.rule.hint}`);
    console.error(`     ${v.text}`);
  }
  console.error("");
  process.exit(1);
}
console.log(`✓ 정직성 카피 가드 통과 (${files.length}개 파일, 위반 0)`);
