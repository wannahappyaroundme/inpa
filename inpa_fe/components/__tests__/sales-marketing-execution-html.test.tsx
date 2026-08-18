import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { JSDOM } from "jsdom";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

// 실행판 HTML은 브라우저의 실제 시계(new Date())로 '오늘'을 계산한다.
// 실제 날짜에 기대면 작성 시점(2026-08-03)이 지난 뒤부터 '오늘 할 일' 검증이 깨지므로,
// 테스트 시계를 작성 시점으로 고정한다. 고정 시각은 KST 오전 10시(UTC 01시)라
// 서버 표준시가 UTC든 KST든 같은 날짜(2026-08-03)로 읽힌다.
const FIXED_NOW = new Date("2026-08-03T10:00:00+09:00");

type ExecutionApi = {
  storageKey: string;
  buildDefaultState: () => Record<string, any>;
  normalizeState: (input: unknown) => Record<string, any>;
  getState: () => Record<string, any>;
  setState: (state: Record<string, any>) => void;
  calculateKpis: (state: Record<string, any>) => Array<Record<string, any>>;
  saveState: () => void;
  exportState: () => void;
  importState: (file: File) => void;
  resetState: () => void;
  buildMonthCells: (month: string) => Array<Record<string, any>>;
  getTodayPresentationDate: (
    state: Record<string, any>,
    today?: string,
  ) => string;
  getOverdueTasks: (
    state: Record<string, any>,
    date: string,
  ) => Array<Record<string, any>>;
  buildOfficialTargets: () => Array<Record<string, any>>;
  buildMonthlyGoals: () => Array<Record<string, any>>;
  buildRouteClusters: () => Array<Record<string, any>>;
  getFilteredTargets: (
    state: Record<string, any>,
    overrides?: Record<string, unknown>,
  ) => Array<Record<string, any>>;
  buildMapUrl: (provider: "naver" | "kakao", address: string) => string;
};

const artifactPath = resolve(
  process.cwd(),
  "../docs/strategy/inpa-sales-marketing-execution.html",
);

async function loadDashboard() {
  const html = readFileSync(artifactPath, "utf8");
  const runtimeErrors: unknown[] = [];
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    resources: "usable",
    url: "https://inpa.local/execution",
    pretendToBeVisual: true,
    beforeParse(window) {
      // JSDOM은 별도 실행 영역이라 vitest 가짜 시계가 자동으로 적용되지 않는다.
      // 고정된 바깥쪽 Date를 주입해야 실행판 스크립트도 같은 '오늘'을 본다.
      (window as unknown as { Date: DateConstructor }).Date =
        globalThis.Date as DateConstructor;
      window.alert = () => undefined;
      window.confirm = () => true;
      window.addEventListener("error", (event) => runtimeErrors.push(event.error));
      window.addEventListener("unhandledrejection", (event) =>
        runtimeErrors.push(event.reason),
      );
    },
  });

  await new Promise<void>((resolveReady) => {
    if (dom.window.document.readyState === "complete") {
      resolveReady();
      return;
    }
    dom.window.addEventListener("load", () => resolveReady(), { once: true });
  });

  return { dom, html, runtimeErrors };
}

function getApi(dom: JSDOM) {
  return (dom.window as unknown as { InpaExecution: ExecutionApi }).InpaExecution;
}

describe("standalone sales and marketing execution dashboard", () => {
  beforeAll(() => {
    // shouldAdvanceTime: JSDOM 로드 완료가 타이머에 의존하므로 시계는 멈추지 않고 흐르게 둔다.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(FIXED_NOW);
  });

  afterAll(() => {
    vi.useRealTimers();
  });

  it("ships the complete single-file plan without external runtime dependencies", async () => {
    const { dom, html, runtimeErrors } = await loadDashboard();
    const api = getApi(dom);
    const defaults = api.buildDefaultState();

    expect(runtimeErrors).toEqual([]);
    expect(html).not.toMatch(/<script[^>]+src=/i);
    expect(html).not.toMatch(/<link[^>]+rel=["']stylesheet["']/i);
    expect(html).not.toMatch(/linkedin\.com|spamcheck|불법스팸/i);
    expect(api.storageKey).toBe("inpa-sales-marketing-execution-v1");
    expect(api.exportState).toBeTypeOf("function");
    expect(api.importState).toBeTypeOf("function");
    expect(api.resetState).toBeTypeOf("function");
    expect(defaults.tasks.length).toBeGreaterThanOrEqual(100);
    expect(defaults.scenarios.length).toBeGreaterThanOrEqual(28);
    expect(defaults.augustDailyActions).toHaveLength(20);
    expect(defaults.monthlyGoals).toHaveLength(5);
    expect(defaults.routeClusters).toHaveLength(10);
    expect(defaults.selectionCriteria).toHaveLength(4);
    expect(defaults.sources).toHaveLength(8);
    expect(defaults.fieldPrinciples).toHaveLength(6);
    expect(defaults.augustDailyActions[0]).toMatchObject({
      date: "2026-08-03",
      contactGoal: 18,
      managerAppointments: 4,
    });
    expect(defaults.augustDailyActions.at(-1)).toMatchObject({
      date: "2026-08-28",
      feedbackGoal: 2,
    });
    expect(
      createHash("sha256")
        .update(JSON.stringify(defaults.augustDailyActions))
        .digest("hex"),
    ).toBe("bd36d9de2aed4e54ca55b143847cae970c53b774dd19dd1771e40e3ce6d46ccc");
    expect(defaults.tasks.every((task: any) => task.action && task.date)).toBe(true);

    const dates = defaults.tasks.map((task: any) => task.date).sort();
    expect(dates[0]).toBe("2026-08-03");
    expect(dates.at(-1)).toBe("2026-12-31");

    expect(dom.window.document.querySelector("#todayPanel")).not.toBeNull();
    expect(dom.window.document.querySelector("#targetsPanel")).not.toBeNull();
    expect(dom.window.document.querySelector("#planningPanel")).not.toBeNull();
    expect(dom.window.document.querySelector("#locationsPanel")).not.toBeNull();
    expect(dom.window.document.querySelector("#scenariosPanel")).not.toBeNull();
    expect(dom.window.document.querySelector("#augustExecutionSection")).not.toBeNull();
  });

  it("persists edits and check state in localStorage", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const state = api.getState();

    state.meta.title = "수정한 실행판";
    state.tasks[0].done = true;
    state.tasks[0].actual = 7;
    api.setState(state);
    api.saveState();

    const stored = JSON.parse(
      dom.window.localStorage.getItem(api.storageKey) ?? "{}",
    );
    expect(stored.meta.title).toBe("수정한 실행판");
    expect(stored.tasks[0].done).toBe(true);
    expect(stored.tasks[0].actual).toBe(7);
  });

  it("adds and deletes editable records through the dashboard controls", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const initialTargets = api.getState().targets.length;

    const addButton = dom.window.document.querySelector<HTMLButtonElement>(
      'button[data-action="add-target"]',
    );
    expect(addButton).not.toBeNull();
    addButton?.click();
    expect(api.getState().targets).toHaveLength(initialTargets + 1);

    const addedTarget = api.getState().targets.at(-1);
    const deleteButton = dom.window.document.querySelector<HTMLButtonElement>(
      `button[data-action="delete-record"][data-collection="targets"][data-id="${addedTarget.id}"]`,
    );
    expect(deleteButton).not.toBeNull();
    deleteButton?.click();
    expect(api.getState().targets).toHaveLength(initialTargets);
  });

  it("calculates automatic and manually overridden KPI values", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const state = api.buildDefaultState();

    state.tasks[0].metricId = "official_contacts";
    state.tasks[0].actual = 9;
    state.kpis.find((kpi: any) => kpi.id === "official_contacts").manualActual = "";

    let calculated = api.calculateKpis(state);
    expect(calculated.find((kpi) => kpi.id === "official_contacts")?.actual).toBe(9);

    state.kpis.find((kpi: any) => kpi.id === "official_contacts").manualActual = 17;
    calculated = api.calculateKpis(state);
    expect(calculated.find((kpi) => kpi.id === "official_contacts")?.actual).toBe(17);
  });

  it("qualifies final users from repeat-use evidence and normalizes imported rows", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const state = api.buildDefaultState();

    state.partners = [
      {
        id: "partner-qualified",
        name: "반복 사용자",
        company: "원수사",
        branch: "서울",
        role: "팀장",
        careerYears: 5,
        startedAt: "2026-10-01",
        firstValue: true,
        reusedD14: true,
        completedD42: true,
        meaningfulWeeks: 6,
        coreFlows: 2,
        feedbackCount: 3,
        activeWeeksLast4: 3,
        lastUsedAt: "2026-12-20",
        note: "",
      },
    ];

    const calculated = api.calculateKpis(state);
    expect(calculated.find((kpi) => kpi.id === "final_users")?.actual).toBe(1);

    const normalized = api.normalizeState({
      meta: { title: "가져온 실행판" },
      tasks: [{ date: "2026-08-03", action: "연락" }],
      scenarios: "invalid",
    });
    expect(normalized.meta.title).toBe("가져온 실행판");
    expect(normalized.tasks).toHaveLength(1);
    expect(normalized.tasks[0].id).toBeTruthy();
    expect(Array.isArray(normalized.scenarios)).toBe(true);
    expect(normalized.scenarios.length).toBeGreaterThanOrEqual(28);
  });

  it("puts today's checklist first and separates overdue work", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    expect(
      dom.window.document.querySelector<HTMLElement>("#todayPanel")?.hidden,
    ).toBe(false);
    expect(
      dom.window.document.querySelector("#todaySection h2")?.textContent,
    ).toContain("오늘 할 일");

    const state = api.buildDefaultState();
    state.tasks = [
      { ...state.tasks[0], id: "overdue", date: "2026-08-03", done: false },
      { ...state.tasks[1], id: "done", date: "2026-08-03", done: true },
      { ...state.tasks[2], id: "today", date: "2026-08-04", done: false },
    ];

    expect(api.getTodayPresentationDate(state, "2026-08-04")).toBe(
      "2026-08-04",
    );
    expect(api.getOverdueTasks(state, "2026-08-04").map((task) => task.id)).toEqual([
      "overdue",
    ]);
  });

  it("renders an interactive 42-cell month calendar with task checkboxes", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const cells = api.buildMonthCells("2026-08");

    expect(cells).toHaveLength(42);
    expect(dom.window.document.querySelectorAll(".calendar-weekday")).toHaveLength(7);
    expect(dom.window.document.querySelectorAll("[data-calendar-date]")).toHaveLength(42);
    expect(dom.window.document.querySelector('[data-action="calendar-prev"]')).not.toBeNull();
    expect(dom.window.document.querySelector('[data-action="calendar-next"]')).not.toBeNull();
    expect(dom.window.document.querySelector('[data-action="calendar-today"]')).not.toBeNull();

    const visibleCounts = Array.from(
      dom.window.document.querySelectorAll(".calendar-day"),
    ).map((day) => day.querySelectorAll(".calendar-task").length);
    expect(Math.max(...visibleCounts)).toBeLessThanOrEqual(3);
    expect(visibleCounts.some((count) => count > 0)).toBe(true);

    const selectDay = dom.window.document.querySelector<HTMLButtonElement>(
      '[data-action="select-calendar-date"][data-date="2026-08-03"]',
    );
    expect(selectDay).not.toBeNull();
    selectDay?.click();
    expect(api.getState().settings.selectedDate).toBe("2026-08-03");
    expect(
      dom.window.document.querySelector("#calendarDetailTitle")?.textContent,
    ).toContain("8월 3일");

    const firstTask = api.getState().tasks.find(
      (task: any) => task.date === "2026-08-03",
    );
    const calendarCheckbox = dom.window.document.querySelector<HTMLInputElement>(
      `.calendar-task input[data-id="${firstTask.id}"][data-field="done"]`,
    );
    expect(calendarCheckbox).not.toBeNull();
    calendarCheckbox?.click();
    expect(api.getState().tasks.find((task: any) => task.id === firstTask.id).done).toBe(
      true,
    );
    expect(
      dom.window.document.querySelector<HTMLInputElement>(
        `#todaySection input[data-id="${firstTask.id}"][data-field="done"]`,
      )?.checked,
    ).toBe(true);

    const nextMonth = dom.window.document.querySelector<HTMLButtonElement>(
      '[data-action="calendar-next"]',
    );
    nextMonth?.click();
    expect(api.getState().settings.calendarMonth).toBe("2026-09");
    expect(dom.window.document.querySelector(".calendar-month-title")?.textContent).toContain(
      "9월",
    );

    const normalized = api.normalizeState({
      settings: { focusDate: "2026-09-08", monthFilter: "2026-09" },
    });
    expect(normalized.settings.selectedDate).toBe("2026-09-08");
    expect(normalized.settings.calendarMonth).toBe("2026-09");
  });

  it("seeds all 80 researched carrier locations and keeps the priority 40 intact", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const targets = api.buildOfficialTargets();

    expect(targets).toHaveLength(80);
    expect(targets.map((target) => target.rank)).toEqual(
      Array.from({ length: 80 }, (_, index) => index + 1),
    );
    expect(targets.filter((target) => target.phase === "우선 40")).toHaveLength(40);
    expect(targets[0]).toMatchObject({
      id: "official-target-1",
      company: "교보생명",
      branch: "남서울FP",
      cluster: "신도림테크노마트",
      phone: "02-851-2996",
      effectScore: 100,
      isOfficialSeed: true,
    });
    expect(targets[39]).toMatchObject({ rank: 40, branch: "서대문지점" });
    expect(targets[79]).toMatchObject({ rank: 80, branch: "제주지점" });
    expect(
      targets.every(
        (target) =>
          target.address && target.phone && target.source && target.sourceCheckedAt,
      ),
    ).toBe(true);

    const canonicalTargets = targets.map((target) => [
      target.rank,
      target.phase,
      target.week,
      target.region,
      target.cluster,
      target.sector,
      target.company,
      target.channel,
      target.branch,
      target.address,
      target.phone,
      target.managerImpact,
      target.plannerAccess,
      target.officialCertainty,
      target.guroAccess,
      target.recommendedApproach,
      target.source,
    ]);
    expect(
      createHash("sha256").update(JSON.stringify(canonicalTargets)).digest("hex"),
    ).toBe("2a78dcfc77ede9606d7fca6f96b8c0933b80cd998b66fba198c646cb0c0c5f03");
  });

  it("migrates prior browser data without losing user-created targets", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const normalized = api.normalizeState({
      version: 1,
      targets: [
        {
          id: "official-target-1",
          rank: 1,
          isOfficialSeed: true,
          contactStatus: "미팅확정",
          note: "기존 공식 대상 메모 유지",
        },
        {
          id: "my-target",
          company: "직접 추가 회사",
          branch: "직접 추가 거점",
          note: "기존 메모 유지",
        },
      ],
    });

    expect(normalized.version).toBe(2);
    expect(normalized.targets.filter((target: any) => target.isOfficialSeed)).toHaveLength(
      80,
    );
    expect(normalized.targets).toHaveLength(81);
    expect(normalized.targets[0]).toMatchObject({
      id: "official-target-1",
      company: "교보생명",
      contactStatus: "미팅확정",
      note: "기존 공식 대상 메모 유지",
    });
    expect(normalized.targets.at(-1)).toMatchObject({
      id: "my-target",
      company: "직접 추가 회사",
      note: "기존 메모 유지",
    });
  });

  it("uses five persistent, keyboard-friendly execution tabs", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const tabs = Array.from(
      dom.window.document.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    );
    const panels = Array.from(
      dom.window.document.querySelectorAll<HTMLElement>('[role="tabpanel"]'),
    );

    expect(tabs.map((tab) => tab.textContent?.trim())).toEqual([
      "오늘 실행",
      "대상 관리",
      "계획·성과",
      "위치·동선",
      "영업 시나리오",
    ]);
    expect(panels).toHaveLength(5);
    expect(panels.filter((panel) => !panel.hidden)).toHaveLength(1);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");

    tabs[1].click();
    expect(api.getState().settings.activeTab).toBe("targets");
    expect(tabs[1].getAttribute("aria-selected")).toBe("true");
    expect(dom.window.document.querySelector<HTMLElement>("#targetsPanel")?.hidden).toBe(
      false,
    );
  });

  it("filters the priority 40 and all 80 locations by execution fields", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const defaults = api.buildDefaultState();

    const priorityKyobo = api.getFilteredTargets(defaults, {
      targetView: "priority40",
      company: "교보생명",
    });
    expect(priorityKyobo.length).toBeGreaterThan(0);
    expect(priorityKyobo.every((target) => target.rank <= 40)).toBe(true);
    expect(priorityKyobo.every((target) => target.company === "교보생명")).toBe(true);

    const allJeju = api.getFilteredTargets(defaults, {
      targetView: "all80",
      search: "제주",
    });
    expect(allJeju.map((target) => target.rank)).toEqual([77, 78, 79, 80]);
    expect(dom.window.document.querySelector('[data-action="set-target-view"]')).not.toBeNull();
    expect(dom.window.document.querySelector('[data-target-filter="company"]')).not.toBeNull();
  });

  it("includes ten executable route clusters and external address map links", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const routes = api.buildRouteClusters();

    expect(routes).toHaveLength(10);
    expect(routes[0]).toMatchObject({
      order: 1,
      cluster: "신도림테크노마트",
      representativeAddress: "서울 구로구 새말로 97",
      targetCount: 6,
      recommendedDate: "8/5 오전",
    });
    expect(createHash("sha256").update(JSON.stringify(routes)).digest("hex")).toBe(
      "ac62379b211bf949fe78a73fe7ed79422eb1cbf507f90b0f6dc2f811923d78f3",
    );
    expect(api.buildMapUrl("naver", routes[0].representativeAddress)).toBe(
      "https://map.naver.com/p/search/%EC%84%9C%EC%9A%B8%20%EA%B5%AC%EB%A1%9C%EA%B5%AC%20%EC%83%88%EB%A7%90%EB%A1%9C%2097",
    );
    expect(api.buildMapUrl("kakao", routes[0].representativeAddress)).toContain(
      "https://map.kakao.com/link/search/",
    );
    expect(dom.window.document.querySelector("#routeClusterList")).not.toBeNull();
    expect(
      dom.window.document.querySelector('a[data-map-provider="naver"]')?.getAttribute("rel"),
    ).toContain("noopener");
  });

  it("moves all five spreadsheet monthly goals into the planning tab", async () => {
    const { dom } = await loadDashboard();
    const api = getApi(dom);
    const goals = api.buildMonthlyGoals();

    expect(goals).toHaveLength(5);
    expect(goals.map((goal) => goal.month)).toEqual([
      "2026-08",
      "2026-09",
      "2026-10",
      "2026-11",
      "2026-12",
    ]);
    expect(goals[0].finalUsers).toBe(0);
    expect(goals[4].finalUsers).toBe(20);
    expect(dom.window.document.querySelector("#monthlyGoalTable")).not.toBeNull();
  });
});
