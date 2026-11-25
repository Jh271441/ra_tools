import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";

export interface MultiSelectOption {
  value: string;
  label: string;
  group?: string;
  disabled?: boolean;
}

export interface MultiSelectProps {
  id?: string;
  values: string[];
  options: MultiSelectOption[];
  onChange: (nextValues: string[]) => void;
  ariaLabel: string;
  lang: UiLanguage;
  placeholder?: string;
  allLabel?: string;
  disabled?: boolean;
  searchable?: boolean;
  showOnlyThis?: boolean;
  className?: string;
}

/**
 * Shared accessible multi-select dropdown reusing Workbench `.multi-filter` tokens.
 * Supports grouped options, search filtering, Select All / Clear / Only This,
 * Escape / outside-click dismiss, viewport flip, and zero native `<select>`.
 */
export const MultiSelect: React.FC<MultiSelectProps> = ({
  id,
  values,
  options,
  onChange,
  ariaLabel,
  lang,
  placeholder,
  allLabel,
  disabled = false,
  searchable,
  showOnlyThis = true,
  className = "",
}) => {
  const [open, setOpen] = useState(false);
  const [openUpward, setOpenUpward] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const reactId = useId();
  const panelId = id ? `${id}-panel` : `multi-select-panel-${reactId}`;

  const selectedSet = useMemo(() => new Set(values), [values]);
  const enableSearch = searchable ?? options.length > 8;

  const filteredOptions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (opt) =>
        opt.label.toLowerCase().includes(q) ||
        opt.value.toLowerCase().includes(q) ||
        (opt.group || "").toLowerCase().includes(q),
    );
  }, [options, query]);

  const groupedOptions = useMemo(() => {
    const groups = new Map<string, MultiSelectOption[]>();
    for (const opt of filteredOptions) {
      const key = opt.group || "";
      const bucket = groups.get(key) || [];
      bucket.push(opt);
      groups.set(key, bucket);
    }
    return Array.from(groups.entries());
  }, [filteredOptions]);

  const summaryText = useMemo(() => {
    const selectedOptions = options.filter((o) => selectedSet.has(o.value));
    if (selectedOptions.length === 0) {
      return placeholder || allLabel || bilingual(lang, "全部", "All");
    }
    if (selectedOptions.length <= 2) {
      return selectedOptions.map((o) => o.label).join(lang === "en" ? ", " : "、");
    }
    return bilingual(
      lang,
      `${selectedOptions[0].label} 等 ${selectedOptions.length} 项`,
      `${selectedOptions[0].label} +${selectedOptions.length - 1}`,
    );
  }, [options, selectedSet, placeholder, allLabel, lang]);

  useEffect(() => {
    if (!open) {
      setQuery("");
      return;
    }
    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    const handlePosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;
      setOpenUpward(spaceBelow < 260 && spaceAbove > spaceBelow);
      const panelWidth = panelRef.current?.offsetWidth || Math.max(rect.width, 240);
      setAlignRight(rect.left + panelWidth > window.innerWidth - 12 && rect.right > panelWidth);
    };
    handlePosition();
    const rafId = window.requestAnimationFrame(handlePosition);
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown, { passive: true });
    document.addEventListener("keydown", handleKeyDown, true);
    window.addEventListener("resize", handlePosition);
    window.addEventListener("scroll", handlePosition, true);
    return () => {
      window.cancelAnimationFrame(rafId);
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown, true);
      window.removeEventListener("resize", handlePosition);
      window.removeEventListener("scroll", handlePosition, true);
    };
  }, [open]);

  const toggleValue = (val: string) => {
    const next = new Set(values);
    if (next.has(val)) next.delete(val);
    else next.add(val);
    onChange(options.map((o) => o.value).filter((v) => next.has(v)));
  };

  const selectAll = () => {
    onChange(options.filter((o) => !o.disabled).map((o) => o.value));
  };

  const clearAll = () => {
    onChange([]);
  };

  return (
    <div
      ref={rootRef}
      className={`multi-filter ra-react-multiselect${open ? " is-open" : ""}${disabled ? " is-disabled" : ""}${className ? ` ${className}` : ""}`}
      data-open={open ? "true" : "false"}
    >
      <button
        ref={triggerRef}
        id={id}
        type="button"
        className="multi-filter-trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={panelId}
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation();
          if (!disabled) setOpen((prev) => !prev);
        }}
      >
        <span className={`multi-filter-summary${values.length > 0 ? " has-value" : ""}`}>
          {summaryText}
        </span>
        <span className="multi-filter-caret" aria-hidden="true" />
      </button>

      {open && (
        <div
          ref={panelRef}
          id={panelId}
          role="group"
          aria-label={ariaLabel}
          className={`multi-filter-panel is-positioned ra-react-multiselect-panel${openUpward ? " is-upward" : ""}${alignRight ? " is-align-right" : ""}`}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="multi-filter-toolbar">
            <button
              type="button"
              className="multi-filter-action"
              onClick={selectAll}
              disabled={options.length === 0}
            >
              {bilingual(lang, "全选", "Select all")}
            </button>
            <button
              type="button"
              className="multi-filter-action"
              data-multi-clear="true"
              onClick={clearAll}
              disabled={values.length === 0}
            >
              {bilingual(lang, "清空", "Clear")}
            </button>
          </div>

          {enableSearch && (
            <input
              type="search"
              className="multi-filter-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={bilingual(lang, "搜索选项…", "Filter options…")}
              aria-label={bilingual(lang, "搜索选项", "Filter options")}
            />
          )}

          <div className="multi-filter-options" role="listbox" aria-multiselectable="true">
            {filteredOptions.length === 0 ? (
              <div className="ra-multiselect-empty">
                {bilingual(lang, "无匹配选项", "No matching options")}
              </div>
            ) : (
              groupedOptions.map(([groupName, groupItems]) => (
                <div key={groupName || "__default"} className="multi-filter-group">
                  {groupName && <div className="multi-filter-group-label">{groupName}</div>}
                  {groupItems.map((option) => {
                    const checked = selectedSet.has(option.value);
                    return (
                      <div
                        key={option.value}
                        className={`multi-filter-option-row${showOnlyThis ? " has-only" : ""}`}
                      >
                        <label className="multi-filter-option">
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={option.disabled}
                            onChange={() => toggleValue(option.value)}
                          />
                          <span title={option.label}>{option.label}</span>
                        </label>
                        {showOnlyThis && !option.disabled && (
                          <button
                            type="button"
                            className="multi-filter-only"
                            onClick={() => onChange([option.value])}
                          >
                            {bilingual(lang, "仅看", "Only")}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
