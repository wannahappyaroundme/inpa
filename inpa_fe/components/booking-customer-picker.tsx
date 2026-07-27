"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { listCustomers, SALES_STAGES, type CustomerListItem } from "@/lib/api";

export interface BookingCustomerPickerProps {
  value: CustomerListItem | null;
  onChange: (customer: CustomerListItem | null) => void;
  disabled?: boolean;
}

function maskPhone(phone: string | null): string {
  const digits = phone?.replace(/\D/g, "") ?? "";
  if (digits.length >= 8) {
    return `${digits.slice(0, 3)}-****-${digits.slice(-4)}`;
  }
  return "연락처 일부 숨김";
}

function stageLabel(stage: CustomerListItem["sales_stage"]): string {
  return SALES_STAGES.find((item) => item.key === stage)?.label ?? "";
}

export function BookingCustomerPicker({ value, onChange, disabled = false }: BookingCustomerPickerProps) {
  const [query, setQuery] = useState(value?.name ?? "");
  const [results, setResults] = useState<CustomerListItem[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [activeIndex, setActiveIndex] = useState(-1);
  const [open, setOpen] = useState(true);
  const requestGeneration = useRef(0);
  const selectedRef = useRef(Boolean(value));
  const valueRef = useRef({ id: value?.id ?? null, name: value?.name ?? "" });
  const inputId = useId();
  const listboxId = `${inputId}-listbox`;

  const load = useCallback(async (search: string) => {
    const generation = ++requestGeneration.current;
    setStatus("loading");
    setActiveIndex(-1);
    try {
      const response = await listCustomers({ page: 1, search: search.trim() || undefined });
      if (generation !== requestGeneration.current) return;
      setResults(response.results);
      setStatus("success");
    } catch {
      if (generation !== requestGeneration.current) return;
      setResults([]);
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(query), 300);
    return () => {
      window.clearTimeout(timer);
      requestGeneration.current += 1;
    };
  }, [load, query]);

  useEffect(() => {
    const nextValue = { id: value?.id ?? null, name: value?.name ?? "" };
    if (valueRef.current.id === nextValue.id && valueRef.current.name === nextValue.name) return;
    valueRef.current = nextValue;
    selectedRef.current = Boolean(value);
    setQuery(value?.name ?? "");
    setResults([]);
    setActiveIndex(-1);
  }, [value?.id, value?.name]);

  const choose = (customer: CustomerListItem) => {
    selectedRef.current = true;
    valueRef.current = { id: customer.id, name: customer.name };
    setQuery(customer.name);
    setOpen(false);
    setActiveIndex(-1);
    onChange(customer);
  };

  const handleInputChange = (next: string) => {
    if (selectedRef.current) {
      selectedRef.current = false;
      valueRef.current = { id: null, name: "" };
      onChange(null);
    }
    setQuery(next);
    setOpen(true);
    setActiveIndex(-1);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (results.length === 0) {
        setActiveIndex(-1);
        return;
      }
      setOpen(true);
      setActiveIndex((current) => Math.min(current + 1, results.length - 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (results.length === 0) {
        setActiveIndex(-1);
        return;
      }
      setActiveIndex((current) => Math.max(current - 1, 0));
      return;
    }
    if (event.key === "Enter" && open && activeIndex >= 0 && results[activeIndex]) {
      event.preventDefault();
      choose(results[activeIndex]);
    }
  };

  const showList = open && !disabled;
  const showsListbox = showList && status === "success" && results.length > 0;

  return (
    <div className="relative">
      <label className="mb-2 block text-sm font-bold text-ink" htmlFor={inputId}>고객 선택</label>
      <input
        id={inputId}
        role="combobox"
        aria-label="고객 선택"
        aria-autocomplete="list"
        aria-expanded={showsListbox}
        aria-controls={showsListbox ? listboxId : undefined}
        aria-activedescendant={activeIndex >= 0 && showsListbox ? `${listboxId}-option-${activeIndex}` : undefined}
        value={query}
        disabled={disabled}
        onChange={(event) => handleInputChange(event.target.value)}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        placeholder="등록한 고객을 찾아보세요"
        className="min-h-11 w-full rounded-xl border border-line bg-white px-3 text-[15px] text-ink outline-none placeholder:text-ink3 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 disabled:bg-surface disabled:text-ink3"
      />

      {showList && (
        <div className="mt-2 overflow-hidden rounded-xl border border-line bg-white shadow-card">
          {status === "loading" && <p role="status" className="px-3 py-3 text-sm text-ink2">고객을 찾고 있어요.</p>}
          {status === "error" && (
            <div role="alert" className="px-3 py-3 text-sm text-ink2">
              <p>고객 목록을 다시 불러올 수 있어요.</p>
              <button type="button" onClick={() => void load(query)} className="mt-2 min-h-11 rounded-lg px-3 font-bold text-indigo-700 hover:bg-indigo-50">
                다시 불러오기
              </button>
            </div>
          )}
          {status === "success" && results.length === 0 && (
            <div className="px-3 py-3 text-sm text-ink2">
              <p>고객을 먼저 추가하면 바로 예약 안내를 만들 수 있어요.</p>
              <a href="/customers" className="mt-2 inline-flex min-h-11 items-center rounded-lg px-3 font-bold text-indigo-700 hover:bg-indigo-50">고객 추가하기</a>
            </div>
          )}
          {showsListbox && (
            <ul id={listboxId} role="listbox" aria-label="고객 검색 결과" className="max-h-64 overflow-y-auto p-1">
              {results.map((customer, index) => (
                <li
                  key={customer.id}
                  id={`${listboxId}-option-${index}`}
                  role="option"
                  aria-selected={activeIndex === index}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => choose(customer)}
                  className={`flex min-h-11 cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-surface ${activeIndex === index ? "bg-indigo-50" : ""}`}
                >
                  <span>
                    <span className="block font-bold text-ink">{customer.name}</span>
                    <span className="block text-xs text-ink3">{maskPhone(customer.mobile_phone_number)}</span>
                  </span>
                  <span className="rounded-md bg-surface px-2 py-1 text-xs font-bold text-ink2">{stageLabel(customer.sales_stage)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
