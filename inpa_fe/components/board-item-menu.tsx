"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

type BoardItemMenuProps = {
  canManage: boolean;
  editHref?: string;
  onEdit?: () => void;
  onDelete: () => void;
  onReport: () => void;
  deleteDisabled?: boolean;
  menuLabel?: string;
};

export function BoardItemMenu({
  canManage,
  editHref,
  onEdit,
  onDelete,
  onReport,
  deleteDisabled = false,
  menuLabel = "게시글 메뉴",
}: BoardItemMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuItemsRef = useRef<HTMLElement[]>([]);

  function focusItem(index: number) {
    const items = menuItemsRef.current.filter((item) => !item.hasAttribute("disabled"));
    if (items.length) items[(index + items.length) % items.length].focus();
  }

  function closeAndFocusTrigger() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    function closeOnOutsideClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        closeAndFocusTrigger();
      }
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeAndFocusTrigger();
      }
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  useEffect(() => {
    if (open) focusItem(0);
  }, [open]);

  return (
    <div className="relative shrink-0" ref={menuRef}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="w-8 h-8 rounded-lg flex items-center justify-center text-ink3 hover:bg-surface2 text-[18px]"
        aria-label="더보기"
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <span aria-hidden>⋯</span>
      </button>
      {open && (
        <div
          role="menu"
          aria-label={menuLabel}
          onKeyDown={(event) => {
            const items = menuItemsRef.current.filter((item) => !item.hasAttribute("disabled"));
            const index = items.indexOf(document.activeElement as HTMLElement);
            if (event.key === "ArrowDown") { event.preventDefault(); focusItem(index + 1); }
            if (event.key === "ArrowUp") { event.preventDefault(); focusItem(index - 1); }
            if (event.key === "Home") { event.preventDefault(); focusItem(0); }
            if (event.key === "End") { event.preventDefault(); focusItem(-1); }
            if (event.key === "Tab") setOpen(false);
          }}
          className="absolute right-0 top-9 z-20 w-32 rounded-xl bg-surface border border-line shadow-lg py-1"
        >
          {canManage ? (
            <>
              {editHref ? (
                <Link
                  href={editHref}
                  role="menuitem"
                  ref={(item) => { if (item) menuItemsRef.current[0] = item; }}
                  className="block px-4 py-2 text-[13px] text-ink hover:bg-surface2"
                  onClick={() => setOpen(false)}
                >
                  수정
                </Link>
              ) : (
                <button
                  type="button"
                  role="menuitem"
                  ref={(item) => { if (item) menuItemsRef.current[0] = item; }}
                  onClick={() => { setOpen(false); onEdit?.(); }}
                  className="w-full text-left px-4 py-2 text-[13px] text-ink hover:bg-surface2"
                >
                  수정
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                ref={(item) => { if (item) menuItemsRef.current[1] = item; }}
                disabled={deleteDisabled}
                onClick={() => { setOpen(false); onDelete(); }}
                className="w-full text-left px-4 py-2 text-[13px] text-danger hover:bg-surface2 disabled:opacity-60"
              >
                삭제
              </button>
            </>
          ) : (
            <button
              type="button"
              role="menuitem"
              ref={(item) => { if (item) menuItemsRef.current[0] = item; }}
              onClick={() => { setOpen(false); onReport(); }}
              className="w-full text-left px-4 py-2 text-[13px] text-danger hover:bg-surface2"
            >
              신고
            </button>
          )}
        </div>
      )}
    </div>
  );
}
