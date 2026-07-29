import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomerListItem, SalesStage } from "@/lib/api";
import CustomersPage from "@/app/customers/page";

const api = vi.hoisted(() => ({
  listAllCustomers: vi.fn(),
  listCustomers: vi.fn(),
  updateCustomer: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));
vi.mock("@/lib/useAuthGuard", () => ({ useAuthGuard: () => true }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/components/app-nav", () => ({ AppNav: () => null }));
vi.mock("@/components/self-diagnosis-share", () => ({
  SelfDiagnosisShare: () => null,
}));
vi.mock("@/components/customer-create-modal", () => ({
  CustomerCreateModal: () => null,
}));
vi.mock("@/components/customer-bulk-modal", () => ({
  CustomerBulkModal: () => null,
}));

const customer = (id: number, salesStage: SalesStage): CustomerListItem => ({
  id,
  name: `고객 ${id}`,
  gender: "1",
  birth_day: "1988-01-01",
  mobile_phone_number: `010-1000-${String(id).padStart(4, "0")}`,
  consent_overseas_at: null,
  color: null,
  avatar_label: "",
  tags: [],
  family_count: 0,
  memo_count: 0,
  sales_stage: salesStage,
  status: "active",
  share_token: null,
  created_at: "2026-07-01T00:00:00Z",
  lead_source: "direct",
  last_contacted_at: "2026-07-28T00:00:00Z",
  is_favorite: false,
  is_pinned: false,
  insurance_age: 39,
  job_risk_grade: 1,
  marketing_consent: "none",
  personal_info_consent: "agreed",
});

const rows = [
  ...Array.from({ length: 14 }, (_, index) => customer(index + 1, "db")),
  ...Array.from({ length: 12 }, (_, index) => customer(index + 15, "contact")),
  ...Array.from({ length: 12 }, (_, index) => customer(index + 27, "meeting")),
  ...Array.from({ length: 12 }, (_, index) => customer(index + 39, "contract")),
];

describe("customers full board", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listAllCustomers.mockResolvedValue(rows);
    api.listCustomers.mockResolvedValue({
      count: 50,
      next: "/api/v1/customers/?page=2",
      previous: null,
      results: rows.slice(0, 20),
    });
  });

  it("shows stage totals from every customer page", async () => {
    render(<CustomersPage />);

    expect(await screen.findByRole("button", { name: "DB 14" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "TA 12" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "FA 12" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "청약 12" })).toBeTruthy();
    expect(api.listAllCustomers).toHaveBeenCalled();
  });
});
