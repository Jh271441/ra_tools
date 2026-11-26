import React, { useEffect, useId, useRef } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { useFocusTrap } from "../../core/shortcutManager";

export interface ModalDialogProps {
  open: boolean;
  title: string;
  lang: UiLanguage;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}

export const ModalDialog: React.FC<ModalDialogProps> = ({
  open,
  title,
  lang,
  onClose,
  children,
  footer,
  wide = false,
}) => {
  const titleId = useId();
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  const backdropPressRef = useRef(false);

  onCloseRef.current = onClose;
  useFocusTrap(open, cardRef, "modal");

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    cardRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.isComposing || event.keyCode === 229) return;
      if (event.key === "Escape") {
        // Let open dropdowns handle Escape first without closing the modal.
        if (document.querySelector(".ra-react-select.is-open, .ra-react-multiselect.is-open")) return;
        event.preventDefault();
        onCloseRef.current();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="ra-modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        backdropPressRef.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        if (backdropPressRef.current && event.target === event.currentTarget) {
          onCloseRef.current();
        }
        backdropPressRef.current = false;
      }}
    >
      <div
        ref={cardRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`dialog-card ra-modal-card${wide ? " ra-modal-wide" : ""}`}
        onMouseDown={(event) => {
          backdropPressRef.current = false;
          event.stopPropagation();
        }}
      >
        <div className="dialog-heading">
          <h2 id={titleId}>{title}</h2>
          <button
            type="button"
            className="icon-button"
            aria-label={bilingual(lang, "关闭", "Close")}
            onClick={() => onCloseRef.current()}
          >
            ×
          </button>
        </div>
        <div className="ra-modal-body">{children}</div>
        {footer && <div className="dialog-actions">{footer}</div>}
      </div>
    </div>
  );
};
