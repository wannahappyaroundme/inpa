#!/usr/bin/env node
/**
 * 정직성 카피 가드 (P8c) — 렌더링 문자열의 em-dash(—)를 자동 차단한다.
 *
 * 배경: PM 레드라인 "사용자 문구에 em-dash(—, U+2014) 금지"("AI 티")를 사람 검수에만 맡기면
 *      언젠가 샌다. 소스에서 기계적으로 잡아 CI 게이트로 막는다. ★ 코드 주석은 예외(허용).
 *
 * 규칙은 전역으로는 em-dash·'준비 중'만 둔다: 오탐 0(한글 UI에서 —는 언제나 불필요). '안전/심의완료'
 * 같은 단어 기반 전역 규칙은 정당한 언급(부인 문구·규칙 설명)까지 잡는 오탐이 커서 의도적으로 제외했다.
 * 필요하면 RULES 배열에 신중히(오탐 검증 후) 추가하면 된다. 규칙에 paths 를 주면 그 경로에만 적용된다.
 *
 * ★ 권유 단어 규칙(#23)은 '고객 대면 라우트'(app/s·b·c·d·p)에만 적용 — §97 부당승환·금소법 권유
 *   규제 자동 방어(dev/14). 서버측 대응 가드: inpa_be/inpa/core/copyguard.py (동일 패턴 세트).
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

// 고객 대면(비로그인 공개) 라우트 — 권유 단어 규칙은 여기만 검사(설계사 내부 화면은 규칙 설명 등 정당 언급 허용).
const CUSTOMER_ROUTES = ["app/s", "app/b", "app/c", "app/d", "app/p"];
const ADVICE_HINT = "고객 대면 화면 권유어 금지(§97·금소법). 사실 서술·중립 표현으로 바꾸세요.";

// 렌더 카피에 절대 없어야 하는 표기(주석 제거 후 검사). 추가할 땐 여기만 늘리면 됨(오탐 검증 필수).
// paths(선택): 배열로 주면 그 디렉터리 하위 파일에만 적용. 없으면 전역.
const RULES = [
  { name: "em-dash(—)", re: /—/, hint: "—는 금지. 쉼표·마침표·콜론·괄호·한글 조사로 바꾸세요." },
  // §6c 긍정 프레임: '준비 중/준비중'(beta-sounding, 없는 기능 광고) 금지 — 다음 행동으로 재서술.
  { name: "준비 중", re: /준비\s?중/, hint: "'준비 중'은 금지. 지금 가능한 다음 행동으로 바꿔 쓰세요(예: '관리자 설정 후 연결할 수 있어요')." },
  // #23 권유 단어 블랙리스트 — 고객 대면 라우트 한정. '추천인'(referrer)은 부정형 전방탐색으로 제외.
  { name: "권유어(추천)", re: /추천(?!인)/, paths: CUSTOMER_ROUTES, hint: ADVICE_HINT },
  { name: "권유어(갈아타)", re: /갈아타/, paths: CUSTOMER_ROUTES, hint: ADVICE_HINT },
  { name: "권유어(해지 유도)", re: /해지하(세요|시는 게|시길)/, paths: CUSTOMER_ROUTES, hint: ADVICE_HINT },
  { name: "권유어(더 유리)", re: /더 유리/, paths: CUSTOMER_ROUTES, hint: ADVICE_HINT },
  { name: "권유어(가입하세요)", re: /가입하세요/, paths: CUSTOMER_ROUTES, hint: ADVICE_HINT },
  { name: "권유어(전환하세요)", re: /전환하세요/, paths: CUSTOMER_ROUTES, hint: ADVICE_HINT },
];

/** rule.paths 가 있으면 해당 경로(디렉터리) 하위 파일에만 적용. */
function ruleApplies(rule, relPath) {
  if (!rule.paths) return true;
  const p = relPath.split(path.sep).join("/");
  return rule.paths.some((prefix) => p === prefix || p.startsWith(prefix + "/"));
}

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
  const rel = path.relative(base, file);
  const rules = RULES.filter((r) => ruleApplies(r, rel));
  if (!rules.length) continue;
  const raw = fs.readFileSync(file, "utf8");
  const original = raw.split("\n");
  const scanned = stripComments(raw).split("\n");
  for (let i = 0; i < scanned.length; i++) {
    for (const rule of rules) {
      if (rule.re.test(scanned[i])) {
        violations.push({ file: rel, line: i + 1, rule, text: (original[i] || "").trim() });
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
