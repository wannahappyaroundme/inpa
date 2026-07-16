"use client";

import { track } from "@vercel/analytics";
import { Check, Maximize2, X } from "lucide-react";
import Image from "next/image";
import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  PRODUCT_SCREENS,
  type ProductScreen,
  type ProductScreenId,
  getAdjacentProductScreenIndex,
  getProductGalleryIds,
} from "@/lib/test-landing-content";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function galleryTrack(name: string, screen: ProductScreenId) {
  try {
    track(name, { screen });
  } catch {
    // 계측 실패는 화면 이용을 막지 않는다.
  }
}

export function TestProductGallery() {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [zoomedScreen, setZoomedScreen] = useState<ProductScreen | null>(null);
  const [failedImages, setFailedImages] = useState<
    Partial<Record<ProductScreenId, true>>
  >({});
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const zoomTriggerRef = useRef<HTMLButtonElement | null>(null);
  const wasZoomOpenRef = useRef(false);

  const selectedScreen = PRODUCT_SCREENS[selectedIndex];
  const selectedIds = getProductGalleryIds(selectedScreen.id);

  const selectScreen = useCallback((index: number, moveFocus: boolean) => {
    setSelectedIndex(index);
    galleryTrack("landing_test_product_tab", PRODUCT_SCREENS[index].id);

    if (moveFocus) {
      requestAnimationFrame(() => tabRefs.current[index]?.focus());
    }
  }, []);

  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;

    event.preventDefault();
    selectScreen(
      getAdjacentProductScreenIndex(currentIndex, event.key),
      true,
    );
  };

  const openZoom = (screen: ProductScreen, trigger: HTMLButtonElement) => {
    zoomTriggerRef.current = trigger;
    setZoomedScreen(screen);
    galleryTrack("landing_test_product_zoom", screen.id);
  };

  const closeZoom = useCallback(() => {
    setZoomedScreen(null);
  }, []);

  useEffect(() => {
    if (!zoomedScreen) return;

    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    const handleDialogKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeZoom();
        return;
      }

      if (event.key !== "Tab" || !dialogRef.current) return;

      const focusableElements = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );

      if (focusableElements.length === 0) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;
      const focusIsInside = dialogRef.current.contains(activeElement);

      if (event.shiftKey && (activeElement === firstElement || !focusIsInside)) {
        event.preventDefault();
        lastElement.focus();
      } else if (
        !event.shiftKey &&
        (activeElement === lastElement || !focusIsInside)
      ) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener("keydown", handleDialogKeyDown);

    return () => {
      document.removeEventListener("keydown", handleDialogKeyDown);
      document.body.style.overflow = previousBodyOverflow;
    };
  }, [closeZoom, zoomedScreen]);

  useEffect(() => {
    if (zoomedScreen) {
      wasZoomOpenRef.current = true;
      return;
    }

    if (wasZoomOpenRef.current) {
      wasZoomOpenRef.current = false;
      zoomTriggerRef.current?.focus();
    }
  }, [zoomedScreen]);

  const markImageFailed = (screenId: ProductScreenId) => {
    setFailedImages((current) =>
      current[screenId] ? current : { ...current, [screenId]: true },
    );
  };

  return (
    <>
      <div
        role="tablist"
        aria-label="인파 실제 화면 선택"
        aria-orientation="horizontal"
        className="mt-10 grid grid-cols-2 gap-2 rounded-3xl border border-[var(--line)] bg-white p-2 shadow-sm sm:grid-cols-5"
      >
        {PRODUCT_SCREENS.map((screen, index) => {
          const isSelected = selectedIndex === index;
          const ids = getProductGalleryIds(screen.id);

          return (
            <button
              key={screen.id}
              ref={(element) => {
                tabRefs.current[index] = element;
              }}
              type="button"
              role="tab"
              id={ids.tabId}
              aria-selected={isSelected}
              aria-controls={ids.panelId}
              tabIndex={isSelected ? 0 : -1}
              className={`flex min-h-14 items-center justify-center gap-2 rounded-2xl border px-3 py-2 text-sm font-extrabold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand)] sm:min-h-16 ${
                isSelected
                  ? "border-[var(--brand)] bg-[var(--accent-tint)] text-[var(--brand-ink)] shadow-sm"
                  : "border-transparent text-[var(--ink-2)] hover:border-[var(--line-2)] hover:bg-[var(--surface-2)]"
              } last:col-span-2 sm:last:col-span-1`}
              onClick={() => selectScreen(index, false)}
              onKeyDown={(event) => handleTabKeyDown(event, index)}
            >
              <span>{screen.label}</span>
              {isSelected && (
                <span className="rounded-full bg-[var(--brand)] px-2 py-0.5 text-[10px] text-white">
                  선택됨
                </span>
              )}
            </button>
          );
        })}
      </div>

      {PRODUCT_SCREENS.map((screen, index) => {
        if (index === selectedIndex) return null;

        const ids = getProductGalleryIds(screen.id);

        return (
          <div
            key={screen.id}
            role="tabpanel"
            id={ids.panelId}
            aria-labelledby={ids.tabId}
            hidden
          />
        );
      })}

      <article
        key={selectedScreen.id}
        role="tabpanel"
        id={selectedIds.panelId}
        aria-labelledby={selectedIds.tabId}
        tabIndex={0}
        data-screen-id={selectedScreen.id}
        className="mt-5 overflow-hidden rounded-3xl border border-[var(--line)] bg-white shadow-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand)]"
      >
        <div className="p-6 sm:p-8">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-[var(--accent-tint)] px-3 py-1 text-xs font-extrabold text-[var(--brand)]">
              {selectedScreen.label}
            </span>
            {selectedScreen.privacyNote && (
              <span className="rounded-full bg-[var(--surface-2)] px-3 py-1 text-xs font-semibold text-[var(--ink-3)]">
                {selectedScreen.privacyNote}
              </span>
            )}
          </div>
          <h3 className="mt-4 break-keep text-2xl font-extrabold text-[var(--ink)] sm:text-3xl">
            {selectedScreen.title}
          </h3>
          <p className="mt-3 max-w-3xl break-keep text-sm leading-6 text-[var(--ink-2)] sm:text-base sm:leading-7">
            {selectedScreen.description}
          </p>
          <ul className="mt-6 grid gap-3 sm:grid-cols-3">
            {selectedScreen.highlights.map((highlight) => (
              <li
                key={highlight}
                className="flex items-start gap-2 text-sm font-semibold text-[var(--ink-2)]"
              >
                <Check
                  className="mt-0.5 shrink-0 text-[var(--success-ink)]"
                  size={17}
                  strokeWidth={2.4}
                  aria-hidden
                />
                <span className="break-keep">{highlight}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="relative overflow-hidden border-t border-[var(--line)] bg-[#edf1f8]">
          <Image
            src={selectedScreen.image}
            alt={selectedScreen.imageAlt}
            width={selectedScreen.width}
            height={selectedScreen.height}
            sizes="(max-width: 639px) 720px, (max-width: 1280px) calc(100vw - 48px), 1152px"
            className="block h-auto w-full min-w-[720px] max-w-none object-left-top sm:min-w-0 sm:max-w-full"
            onError={() => markImageFailed(selectedScreen.id)}
          />
          {failedImages[selectedScreen.id] && (
            <div
              className="absolute inset-0 flex items-center justify-center bg-[var(--surface-2)] px-6 text-center text-sm font-semibold text-[var(--ink-2)]"
              role="status"
            >
              화면 설명과 주요 내용은 위에서 확인할 수 있어요.
            </div>
          )}
          <button
            ref={zoomTriggerRef}
            type="button"
            className="absolute bottom-4 right-4 z-10 inline-flex min-h-11 items-center gap-2 rounded-xl border border-white/80 bg-white/95 px-4 py-2 text-sm font-extrabold text-[var(--brand-ink)] shadow-lg backdrop-blur hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand)]"
            aria-label={`${selectedScreen.title} 화면 확대해서 보기`}
            onClick={(event) => openZoom(selectedScreen, event.currentTarget)}
          >
            <Maximize2 size={17} aria-hidden />
            확대 보기
          </button>
        </div>
      </article>

      {zoomedScreen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-[#07142f]/85 p-3 backdrop-blur-sm sm:p-6"
          onClick={(event) => {
            if (event.target === event.currentTarget) closeZoom();
          }}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={getProductGalleryIds(zoomedScreen.id).dialogTitleId}
            tabIndex={-1}
            className="max-h-[94dvh] w-[min(96vw,1500px)] overflow-y-auto rounded-3xl bg-white p-3 shadow-2xl focus:outline-none sm:p-5"
          >
            <div className="flex items-start justify-between gap-4 px-2 pb-3 sm:px-1">
              <div>
                <h2
                  id={getProductGalleryIds(zoomedScreen.id).dialogTitleId}
                  className="break-keep text-lg font-extrabold text-[var(--brand-ink)] sm:text-xl"
                >
                  {zoomedScreen.title}
                </h2>
                {zoomedScreen.privacyNote && (
                  <p className="mt-1 text-xs font-semibold text-[var(--ink-3)]">
                    {zoomedScreen.privacyNote}
                  </p>
                )}
              </div>
              <button
                ref={closeButtonRef}
                type="button"
                className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-[var(--line)] bg-white text-[var(--ink-2)] hover:border-[var(--brand)] hover:text-[var(--brand)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand)]"
                aria-label={`${zoomedScreen.title} 확대 보기 닫기`}
                onClick={closeZoom}
              >
                <X size={21} aria-hidden />
              </button>
            </div>
            <div className="relative flex justify-center overflow-hidden rounded-2xl border border-[var(--line)] bg-[#edf1f8]">
              <Image
                src={zoomedScreen.image}
                alt={zoomedScreen.imageAlt}
                width={zoomedScreen.width}
                height={zoomedScreen.height}
                sizes="96vw"
                className="h-auto max-h-[calc(94dvh-7rem)] w-auto max-w-full object-contain object-top"
                onError={() => markImageFailed(zoomedScreen.id)}
              />
              {failedImages[zoomedScreen.id] && (
                <div
                  className="absolute inset-0 flex items-center justify-center bg-[var(--surface-2)] px-6 text-center text-sm font-semibold text-[var(--ink-2)]"
                  role="status"
                >
                  화면 설명과 주요 내용은 이전 화면에서 확인할 수 있어요.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
