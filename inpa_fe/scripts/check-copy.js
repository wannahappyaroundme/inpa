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

const ROOTS = ["app", "components", "lib"];
const EXT = new Set([".ts", ".tsx"]);

// 고객 대면(비로그인 공개) 라우트 — 권유 단어 규칙은 여기만 검사(설계사 내부 화면은 규칙 설명 등 정당 언급 허용).
const CUSTOMER_ROUTES = ["app/s", "app/b", "app/c", "app/d", "app/p"];
// 고객 전송용 텍스트를 만드는 모듈 — 설계사 페이지 안이지만 이 텍스트는 고객이 직접 읽으므로 권유어 규칙을
// 여기에도 적용한다(페이지 전체는 정당한 §97 내부 안내 문구 때문에 오탐이라 파일 단위로 분리해 가드한다).
const ADVICE_PATHS = [...CUSTOMER_ROUTES, "lib/compare-export.ts", "lib/copy-library.ts"];
const ADVICE_HINT = "고객 대면 화면 권유어 금지(§97·금소법). 사실 서술·중립 표현으로 바꾸세요.";
const COPY_LIBRARY_PATHS = ["lib/copy-library.ts"];

// 증권 비교 노출면: 기능을 보험 교체 제안이 아니라 여러 증권의 중립 A/B 시각화로 설명한다.
// 내부 API·법무 주석은 호환성과 기록을 위해 유지하므로 렌더링 가능성이 있는 파일만 검사한다.
const MULTI_POLICY_SURFACES = [
  "app/customer/[id]/page.tsx",
  "app/faq/page.tsx",
  "app/onboarding/page.tsx",
  "app/settings/account/page.tsx",
  "app/admin/demo",
  "app/analysis/page.tsx",
  "components/landing-sections.tsx",
  "components/brand-story-sections.tsx",
  "components/charts.tsx",
  "components/insurance-import-cards.tsx",
  "components/insurance-manual-modal.tsx",
  "components/insurance-manual-review.tsx",
  "components/insurance-review-cards.tsx",
  "components/premium-split.tsx",
  "components/upgrade-modal.tsx",
  "lib/landing-content.ts",
  "lib/compare-export.ts",
  "lib/mock.ts",
];

// 렌더 카피에 절대 없어야 하는 표기(주석 제거 후 검사). 추가할 땐 여기만 늘리면 됨(오탐 검증 필수).
// paths(선택): 배열로 주면 그 디렉터리 하위 파일에만 적용. 없으면 전역.
const RULES = [
  { name: "em-dash(—)", re: /—/, hint: "—는 금지. 쉼표·마침표·콜론·괄호·한글 조사로 바꾸세요." },
  // §6c 긍정 프레임: '준비 중/준비중'(beta-sounding, 없는 기능 광고) 금지 — 다음 행동으로 재서술.
  { name: "준비 중", re: /준비\s?중/, hint: "'준비 중'은 금지. 지금 가능한 다음 행동으로 바꿔 쓰세요(예: '관리자 설정 후 연결할 수 있어요')." },
  // #23 권유 단어 블랙리스트 — 고객 대면 라우트 한정. '추천인'(referrer)은 부정형 전방탐색으로 제외.
  { name: "권유어(추천)", re: /추천(?!인)/, paths: ADVICE_PATHS, hint: ADVICE_HINT },
  { name: "권유어(갈아타)", re: /갈아타/, paths: ADVICE_PATHS, hint: ADVICE_HINT },
  { name: "권유어(해지 유도)", re: /해지하(세요|시는 게|시길)/, paths: ADVICE_PATHS, hint: ADVICE_HINT },
  { name: "권유어(더 유리)", re: /더 유리/, paths: ADVICE_PATHS, hint: ADVICE_HINT },
  { name: "권유어(가입하세요)", re: /가입하세요/, paths: ADVICE_PATHS, hint: ADVICE_HINT },
  { name: "권유어(전환하세요)", re: /전환하세요/, paths: ADVICE_PATHS, hint: ADVICE_HINT },
  { name: "가짜 수신거부 번호", re: /080-[0-9]/, paths: COPY_LIBRARY_PATHS, hint: "실제 번호가 없으면 담당 설계사 연락처로 안내하거나 전화 문구를 빼세요." },
  { name: "검증 불가 약속", re: /부담 없이|무조건|확실한|보장됩니다/, paths: COPY_LIBRARY_PATHS, hint: "확인 가능한 사실과 다음 행동 중심으로 바꾸세요." },
  {
    name: "교체 전제 비교 문구",
    re: /현재와 제안|현재 보험과 새 제안|기존과 제안|제안과 나란히|보유 증권과 새 제안|기존.*제안|product:\s*"(?:기존|제안)|["']제안["']|^\s*제안\s*$|labelA\s*=\s*"현재"|유지·전환|갈아타기|승환|비교안내서/,
    paths: MULTI_POLICY_SURFACES,
    hint: "여러 증권의 A/B 시각 비교로 표현하세요.",
  },
];

/** rule.paths 가 있으면 해당 경로(디렉터리) 하위 파일에만 적용. */
function ruleApplies(rule, relPath) {
  if (!rule.paths) return true;
  const p = relPath.split(path.sep).join("/");
  return rule.paths.some((prefix) => p === prefix || p.startsWith(prefix + "/"));
}

/** 주석만 검사 대상에서 제외한다. 문자열·템플릿 리터럴 속 // 및 /* 는 그대로 보존한다. */
function stripComments(src) {
  let result = "";
  let state = "code";
  for (let i = 0; i < src.length; i += 1) {
    const char = src[i];
    const next = src[i + 1];

    if (state === "line-comment") {
      if (char === "\n") {
        state = "code";
        result += char;
      } else {
        result += " ";
      }
      continue;
    }
    if (state === "block-comment") {
      if (char === "*" && next === "/") {
        result += "  ";
        i += 1;
        state = "code";
      } else {
        result += char === "\n" ? "\n" : " ";
      }
      continue;
    }
    if (state === "single" || state === "double" || state === "template") {
      result += char;
      if (char === "\\" && next !== undefined) {
        result += next;
        i += 1;
      } else if ((state === "single" && char === "'")
          || (state === "double" && char === '"')
          || (state === "template" && char === "`")) {
        state = "code";
      }
      continue;
    }

    if (char === "/" && next === "/") {
      result += "  ";
      i += 1;
      state = "line-comment";
    } else if (char === "/" && next === "*") {
      result += "  ";
      i += 1;
      state = "block-comment";
    } else {
      result += char;
      if (char === "'") state = "single";
      else if (char === '"') state = "double";
      else if (char === "`") state = "template";
    }
  }
  return result;
}

function walk(dir, out) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, out);
    else if (EXT.has(path.extname(name))) out.push(p);
  }
}

function scanCopy(base = path.resolve(__dirname, "..")) {
  const files = [];
  for (const r of ROOTS) {
    const d = path.join(base, r);
    if (fs.existsSync(d)) walk(d, files);
  }

  const violations = [];
  const relativeFiles = [];
  for (const file of files) {
    const rel = path.relative(base, file);
    relativeFiles.push(rel);
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
  return { files: relativeFiles, violations };
}

function main() {
  const { files, violations } = scanCopy();
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
}

if (require.main === module) main();

module.exports = { scanCopy, stripComments };
