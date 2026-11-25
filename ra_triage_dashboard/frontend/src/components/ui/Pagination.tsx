import React, { useEffect, useId, useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { UiSelect } from "./UiSelect";

export const CASE_PAGE_SIZES = [10, 20, 50, 100] as const;
export const DEFAULT_CASE_PAGE_SIZE = 20;

export interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  lang: UiLanguage;
  loading?: boolean;
  ariaLabel?: string;
  labelText?: string;
  summaryText?: string;
  showPageUnit?: boolean;
  disableJumpWhenSinglePage?: boolean;
  keepControlsEnabledWhenEmpty?: boolean;
  className?: string;
  onPageChange: (nextPage: number) => void;
  onPageSizeChange: (nextSize: number) => void;
  onClearSelection?: () => void;
}

export const Pagination: React.FC<PaginationProps> = ({
  page,
  pageSize,
  total,
  lang,
  loading = false,
  ariaLabel,
  labelText,
  summaryText,
  showPageUnit = false,
  disableJumpWhenSinglePage = false,
  keepControlsEnabledWhenEmpty = false,
  className,
  onPageChange,
  onPageSizeChange,
  onClearSelection,
}) => {
  const safeSize = CASE_PAGE_SIZES.includes(pageSize as (typeof CASE_PAGE_SIZES)[number])
    ? pageSize
    : DEFAULT_CASE_PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(Math.max(0, total) / safeSize));
  const safePage = Math.max(1, Math.min(totalPages, Math.floor(page) || 1));
  const [jumpInput, setJumpInput] = useState<string>(String(safePage));
  const jumpId = useId();
  const sizeId = useId();

  useEffect(() => {
    setJumpInput(String(safePage));
  }, [safePage]);

  const disabledAll = loading || total <= 0;

  const navigateTo = (target: number) => {
    const clamped = Math.max(1, Math.min(totalPages, target));
    if (clamped === safePage) return;
    onClearSelection?.();
    onPageChange(clamped);
  };

  const handleJump = () => {
    const trimmed = jumpInput.trim();
    if (!trimmed) return;
    const parsed = Number(trimmed);
    if (!Number.isInteger(parsed)) return;
    navigateTo(parsed);
  };

  const pageSizeOptions = CASE_PAGE_SIZES.map((size) => ({
    value: String(size),
    label: String(size),
  }));

  return (
    <nav
      className={
        className
          ? `${className} ra-react-pagination`
          : "case-pagination gallery-pagination ra-react-pagination"
      }
      aria-label={ariaLabel || bilingual(lang, "分页导航", "Pagination")}
    >
      {summaryText !== undefined ? <span>{summaryText}</span> : null}
      <div className="case-pagination-main">
        <button
          type="button"
          className="button button-quiet"
          disabled={disabledAll || safePage <= 1}
          onClick={() => navigateTo(safePage - 1)}
        >
          {bilingual(lang, "上一页", "Previous")}
        </button>

        <span className="ra-pagination-label" aria-live="polite">
          {labelText !== undefined
            ? labelText
            : summaryText !== undefined
              ? total > 0
                ? `${safePage} / ${totalPages}`
                : "— / —"
              : total > 0
                ? `${safePage} / ${totalPages} · ${total.toLocaleString()}`
                : bilingual(lang, "0 条结果", "0 items")}
        </span>

        <button
          type="button"
          className="button button-quiet"
          disabled={disabledAll || safePage >= totalPages}
          onClick={() => navigateTo(safePage + 1)}
        >
          {bilingual(lang, "下一页", "Next")}
        </button>

        <span className="page-jump-control">
          <label htmlFor={jumpId}>{bilingual(lang, "跳至", "Go to")}</label>
          <input
            id={jumpId}
            type="number"
            inputMode="numeric"
            min={1}
            max={totalPages}
            step={1}
            value={jumpInput}
            disabled={
              loading ||
              (!keepControlsEnabledWhenEmpty && total <= 0) ||
              ((summaryText !== undefined || disableJumpWhenSinglePage) && totalPages <= 1)
            }
            aria-label={bilingual(lang, "输入页码", "Enter page number")}
            onChange={(e) => setJumpInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleJump();
              }
            }}
          />
          {summaryText !== undefined || showPageUnit ? (
            <span>{bilingual(lang, "页", "page")}</span>
          ) : null}
          <button
            type="button"
            className="button button-quiet"
            disabled={
              loading ||
              (!keepControlsEnabledWhenEmpty && total <= 0) ||
              ((summaryText !== undefined || disableJumpWhenSinglePage) && totalPages <= 1)
            }
            onClick={handleJump}
          >
            {bilingual(lang, "跳转", "Go")}
          </button>
        </span>
      </div>

      <div className="case-page-size">
        <span>{bilingual(lang, "每页", "Per page")}</span>
        <UiSelect
          id={sizeId}
          value={String(safeSize)}
          options={pageSizeOptions}
          disabled={keepControlsEnabledWhenEmpty ? loading : disabledAll}
          compact
          ariaLabel={bilingual(lang, "每页条数", "Items per page")}
          onChange={(nextVal) => {
            const nextSize = Number(nextVal);
            if (!CASE_PAGE_SIZES.includes(nextSize as (typeof CASE_PAGE_SIZES)[number])) return;
            onClearSelection?.();
            onPageSizeChange(nextSize);
          }}
        />
        <span>{bilingual(lang, "条", "items")}</span>
      </div>
    </nav>
  );
};
