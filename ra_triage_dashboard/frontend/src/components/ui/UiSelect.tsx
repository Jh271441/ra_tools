import React, { useEffect, useId, useMemo, useRef, useState } from "react";

export interface UiSelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface UiSelectProps {
  id?: string;
  value: string;
  options: UiSelectOption[];
  onChange: (value: string) => void;
  ariaLabel: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  compact?: boolean;
}

/**
 * Shared accessible custom select reusing Workbench `.ui-select` tokens.
 * Supports keyboard navigation, Escape/outside-click dismiss, and viewport flip.
 */
export const UiSelect: React.FC<UiSelectProps> = ({
  id,
  value,
  options,
  onChange,
  ariaLabel,
  placeholder = "—",
  disabled = false,
  className = "",
  compact = false,
}) => {
  const [open, setOpen] = useState(false);
  const [openUpward, setOpenUpward] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const [activeIndex, setActiveIndex] = useState<number>(-1);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const reactId = useId();
  const listboxId = id ? `${id}-listbox` : `ui-select-listbox-${reactId}`;

  const selectedIndex = useMemo(
    () => options.findIndex((item) => item.value === value),
    [options, value],
  );
  const selectedOption = selectedIndex >= 0 ? options[selectedIndex] : null;

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDownGlobal = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    const handleResize = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;
      setOpenUpward(spaceBelow < 220 && spaceAbove > spaceBelow);
      const menuWidth = menuRef.current?.offsetWidth || Math.max(rect.width, 220);
      setAlignRight(rect.left + menuWidth > window.innerWidth - 12 && rect.right > menuWidth);
    };
    handleResize();
    const rafId = window.requestAnimationFrame(handleResize);
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown, { passive: true });
    document.addEventListener("keydown", handleKeyDownGlobal, true);
    window.addEventListener("resize", handleResize);
    window.addEventListener("scroll", handleResize, true);
    return () => {
      window.cancelAnimationFrame(rafId);
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDownGlobal, true);
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("scroll", handleResize, true);
    };
  }, [open]);

  const moveActive = (delta: number) => {
    if (!options.length) return;
    let next = activeIndex < 0 ? Math.max(0, selectedIndex) : activeIndex;
    for (let step = 0; step < options.length; step += 1) {
      next = (next + delta + options.length) % options.length;
      if (!options[next]?.disabled) {
        setActiveIndex(next);
        return;
      }
    }
  };

  const commitOption = (option: UiSelectOption) => {
    if (option.disabled) return;
    if (option.value !== value) {
      onChange(option.value);
    }
    setOpen(false);
    triggerRef.current?.focus();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
        setOpen(false);
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
      } else {
        moveActive(1);
      }
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setActiveIndex(selectedIndex >= 0 ? selectedIndex : Math.max(0, options.length - 1));
      } else {
        moveActive(-1);
      }
      return;
    }
    if (event.key === "Home" && open) {
      event.preventDefault();
      const first = options.findIndex((o) => !o.disabled);
      if (first >= 0) setActiveIndex(first);
      return;
    }
    if (event.key === "End" && open) {
      event.preventDefault();
      for (let i = options.length - 1; i >= 0; i -= 1) {
        if (!options[i]?.disabled) {
          setActiveIndex(i);
          break;
        }
      }
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
      } else if (activeIndex >= 0 && options[activeIndex]) {
        commitOption(options[activeIndex]);
      } else {
        setOpen(false);
      }
    }
  };

  return (
    <div
      ref={rootRef}
      className={`ui-select ra-react-select${open ? " is-open" : ""}${compact ? " is-compact" : ""}${className ? ` ${className}` : ""}`}
      data-open={open ? "true" : "false"}
    >
      <button
        ref={triggerRef}
        id={id}
        type="button"
        className="ui-select-trigger"
        role="combobox"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation();
          if (disabled) return;
          setOpen((prev) => {
            const next = !prev;
            if (next) setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
            return next;
          });
        }}
        onKeyDown={handleKeyDown}
      >
        <span className="ui-select-summary">
          {selectedOption ? selectedOption.label : placeholder}
        </span>
        <span className="ui-select-caret" aria-hidden="true" />
      </button>

      {open && (
        <div
          ref={menuRef}
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          className={`ui-select-panel is-positioned ra-react-select-menu${openUpward ? " is-upward" : ""}${alignRight ? " is-align-right" : ""}`}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          {options.map((option, index) => {
            const isSelected = option.value === value;
            const isActive = index === activeIndex;
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                disabled={option.disabled}
                className={`ui-select-option${isSelected ? " is-selected" : ""}${isActive ? " is-active" : ""}`}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => commitOption(option)}
              >
                <span className="ui-select-option-check" aria-hidden="true">
                  {isSelected ? "✓" : ""}
                </span>
                <span className="ui-select-option-label">{option.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
