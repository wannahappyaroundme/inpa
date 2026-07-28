import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  GUIDED_TALK_OBJECTIONS,
  GUIDED_TALK_PLAYBOOKS,
  GUIDED_TALK_VERSION,
  renderGuidedTalk,
  talkScriptsHref,
} from "@/lib/guided-talk-playbooks";

const keyPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const unsafeCopy =
  /자살|무조건|바로 보장|어떤 일이 생겨도|종신토록|자산이 되는|보험아줌마|고졸|파트타이머 아주머니|대외비|정보만|부담가지|통화가능하시죠|괜찮으시죠|관심없어도|언젠가는.*사망|22개의|70%|2005년|72\.8|80\.4|2010년|교보생명|삼성생명|대한생명|여성시대|퍼펙트|Benz|Fax/i;

describe("guided talk playbook registry", () => {
  it("ships two versioned customer playbooks with stable unique keys", () => {
    expect(GUIDED_TALK_VERSION).toMatch(/^\d{4}-\d{2}-\d{2}\.v\d+$/);
    expect(GUIDED_TALK_PLAYBOOKS).toHaveLength(2);
    expect(GUIDED_TALK_PLAYBOOKS.map((playbook) => playbook.key)).toEqual([
      "referred-customer-first-call",
      "first-coverage-review",
    ]);

    const allKeys = [
      ...GUIDED_TALK_PLAYBOOKS.map((playbook) => playbook.key),
      ...GUIDED_TALK_PLAYBOOKS.flatMap((playbook) =>
        playbook.steps.map((step) => step.key),
      ),
      ...Object.keys(GUIDED_TALK_OBJECTIONS),
    ];
    expect(new Set(allKeys)).toHaveLength(allKeys.length);
    for (const key of allKeys) expect(key).toMatch(keyPattern);
  });

  it("keeps the call and meeting scenes separate with complete step contracts", () => {
    expect(GUIDED_TALK_PLAYBOOKS[0].steps).toHaveLength(6);
    expect(GUIDED_TALK_PLAYBOOKS[1].steps).toHaveLength(8);

    const knownObjections = new Set(Object.keys(GUIDED_TALK_OBJECTIONS));
    for (const playbook of GUIDED_TALK_PLAYBOOKS) {
      expect(playbook.title.trim()).not.toBe("");
      expect(playbook.goal.trim()).not.toBe("");
      expect(playbook.durationLabel.trim()).not.toBe("");
      expect(playbook.nextActions.length).toBeGreaterThanOrEqual(2);
      for (const step of playbook.steps) {
        expect(step.title.trim()).not.toBe("");
        expect(step.goal.trim()).not.toBe("");
        expect(step.spokenText.trim()).not.toBe("");
        expect(step.questions.length).toBeLessThanOrEqual(2);
        expect(step.checklist.length).toBeGreaterThan(0);
        for (const objectionKey of step.objectionKeys) {
          expect(knownObjections.has(objectionKey)).toBe(true);
        }
      }
    }
  });

  it("starts each scene with identity, affiliation, insurance purpose, and permission", () => {
    for (const playbook of GUIDED_TALK_PLAYBOOKS) {
      const first = playbook.steps[0];
      expect(first.requiresSalesDisclosure).toBe(true);
      expect(first.spokenText).toContain("{설계사명}");
      expect(first.spokenText).toContain("{소속직책}");
      expect(first.spokenText).toMatch(/보험.*상담|보험.*안내/);
      expect(first.spokenText).toMatch(/될까요|괜찮을까요/);
    }
  });

  it("contains no stale claims, pressure, fear, discrimination, or company promotion", () => {
    const renderedRegistry = JSON.stringify({
      playbooks: GUIDED_TALK_PLAYBOOKS,
      objections: GUIDED_TALK_OBJECTIONS,
    });
    expect(renderedRegistry).not.toMatch(unsafeCopy);
    expect(renderedRegistry).not.toMatch(
      /보험금.*(?:확실|보장)|(?:절감|아낄).*보험료|갈아타|바꾸셔야/,
    );
  });

  it("ends opt-out and repeat-refusal branches without another sales proposal", () => {
    const optOut = GUIDED_TALK_OBJECTIONS["no-more-contact"];
    expect(optOut.terminal).toBe(true);
    expect(optOut.responseText).toMatch(/연락.*마치|연락.*드리지/);
    expect(optOut.responseText).not.toMatch(/다만|그래도|대신|한 번만/);

    for (const objection of Object.values(GUIDED_TALK_OBJECTIONS)) {
      expect(objection.secondRefusalText).toMatch(/마치|존중|연락드리지/);
      expect(objection.secondRefusalText).not.toMatch(
        /다만|그래도|대신|확인해 보|예약|약속/,
      );
    }
  });

  it("offers an explicit close alongside forward choices", () => {
    const steps = GUIDED_TALK_PLAYBOOKS.flatMap(
      (playbook) => playbook.steps,
    );
    for (const key of [
      "call-schedule-choice",
      "meeting-consent",
      "meeting-summary",
    ]) {
      expect(
        steps.find((step) => step.key === key)?.spokenText,
      ).toMatch(/마치|마칠|마쳐/);
    }
    expect(
      GUIDED_TALK_PLAYBOOKS[0].nextActions.map((action) => action.key),
    ).toContain("end-call");
  });

  it("renders complete spoken Korean with empty or real variables", () => {
    const variants = [
      {},
      {
        customer: "김인파",
        planner: "황예진",
        affiliation: "인파지점",
        title: "팀장",
        referrer: "이인파",
      },
    ];

    for (const variables of variants) {
      const rendered = GUIDED_TALK_PLAYBOOKS.flatMap((playbook) =>
        playbook.steps.map((step) =>
          renderGuidedTalk(step.spokenText, variables),
        ),
      );
      for (const text of rendered) {
        expect(text).not.toMatch(/\{[^{}]+\}/);
        expect(text).not.toMatch(/[ \t]{2,}/);
        expect(text).not.toContain("고객 고객님");
        expect(text).not.toContain("님 님");
      }
    }

    const referral = renderGuidedTalk(
      "{소개자명} 님 소개로 연락드렸습니다.",
      {},
    );
    expect(referral).toBe("소개를 받아 연락드렸습니다.");
    expect(
      renderGuidedTalk("{소개자명} 님 소개로 연락드렸습니다.", {
        referrer: "이인파",
      }),
    ).toBe("이인파 님 소개로 연락드렸습니다.");
  });

  it("builds customerId links and leaves no generated customer-name URL", () => {
    expect(
      talkScriptsHref(31, {
        playbook: "referred-customer-first-call",
      }),
    ).toBe(
      "/scripts?customerId=31&playbook=referred-customer-first-call",
    );
    expect(
      talkScriptsHref(31, {
        mode: "quick",
        playbook: "first-coverage-review",
      }),
    ).toBe(
      "/scripts?customerId=31&mode=quick&playbook=first-coverage-review",
    );

    const sources = [
      "components/call-list.tsx",
      "app/customer/[id]/page.tsx",
    ].map((path) => readFileSync(join(process.cwd(), path), "utf8"));
    for (const source of sources) {
      expect(source).not.toContain("scripts?customer=");
      expect(source).toContain("talkScriptsHref");
    }
    expect(sources[1]).toContain('"first-coverage-review"');
  });
});
