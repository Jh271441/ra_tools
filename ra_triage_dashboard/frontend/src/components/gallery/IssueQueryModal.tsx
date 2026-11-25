import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { parseIssueIdsInput } from "../../utils/analysisHelpers";
import { showToast } from "../ui/Toast";

export interface IssueQueryModalProps {
  open: boolean;
  lang: UiLanguage;
  initialIssueIds: readonly string[];
  onApply: (issueIds: string[]) => void;
  onClose: () => void;
}

export const IssueQueryModal: React.FC<IssueQueryModalProps> = ({
  open,
  lang,
  initialIssueIds,
  onApply,
  onClose,
}) => {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [rawText, setRawText] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      setRawText((initialIssueIds || []).join("\n"));
      if (!dialog.open) {
        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "");
      }
      window.requestAnimationFrame(() => inputRef.current?.focus());
    } else if (dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open, initialIssueIds]);

  const parsed = useMemo(() => parseIssueIdsInput(rawText), [rawText]);

  const feedbackText = useMemo(() => {
    if (parsed.invalid.length > 0) {
      const sample = parsed.invalid.slice(0, 4).join(lang === "en" ? ", " : "、");
      const ellipsis = parsed.invalid.length > 4 ? "…" : "";
      return bilingual(
        lang,
        `已识别 ${parsed.ids.length} 个 Issue；无法识别：${sample}${ellipsis}`,
        `${parsed.ids.length} Issues recognized; invalid: ${sample}${ellipsis}`,
      );
    }
    if (parsed.ids.length > 0) {
      return bilingual(
        lang,
        `已识别 ${parsed.ids.length} 个 Issue（重复项已去重）`,
        `${parsed.ids.length} Issues recognized (duplicates removed)`,
      );
    }
    return bilingual(
      lang,
      "输入为空，将清除多 Issue 条件",
      "Empty input will clear the multi-Issue filter",
    );
  }, [parsed, lang]);

  const handleApply = () => {
    if (parsed.invalid.length > 0) {
      showToast(
        bilingual(lang, "请先修正无法识别的 Issue。", "Fix invalid Issue tokens first."),
        true,
      );
      return;
    }
    onApply(parsed.ids);
    onClose();
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <dialog
      ref={dialogRef}
      className="dialog issue-query-dialog"
      id="raIssueQueryDialog"
      aria-labelledby="raIssueQueryTitle"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose();
      }}
    >
      <div className="dialog-card">
        <div className="dialog-heading">
          <div>
            <h2 id="raIssueQueryTitle">
              {bilingual(lang, "多 Issue 精确查询", "Multi-Issue Exact Query")}
            </h2>
            <p className="dialog-copy">
              {bilingual(
                lang,
                "粘贴多个 Issue ID 或 Voyager 链接（支持换行、空格或逗号分隔）。留空后点击应用可清除。",
                "Paste multiple Issue IDs or Voyager URLs (separated by newlines, spaces, or commas). Leave blank and apply to clear.",
              )}
            </p>
          </div>
          <button
            className="icon-button"
            type="button"
            aria-label={bilingual(lang, "关闭", "Close")}
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <label className="issue-query-field">
          <span>{bilingual(lang, "Issue 列表", "Issue list")}</span>
          <textarea
            ref={inputRef}
            rows={7}
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            placeholder={bilingual(
              lang,
              "例如：\ncn38048091\ncn38048237",
              "Example:\ncn38048091\ncn38048237",
            )}
          />
        </label>

        <p
          className={`issue-query-feedback${parsed.invalid.length > 0 ? " is-error" : parsed.ids.length > 0 ? " is-ready" : ""}`}
          role="status"
        >
          {feedbackText}
        </p>

        <div className="dialog-actions">
          <button
            className="button button-quiet"
            type="button"
            onClick={() => setRawText("")}
          >
            {bilingual(lang, "清空", "Clear")}
          </button>
          <button className="button button-quiet" type="button" onClick={onClose}>
            {bilingual(lang, "取消", "Cancel")}
          </button>
          <button className="button button-primary" type="button" onClick={handleApply}>
            {bilingual(lang, "应用筛选", "Apply filter")}
          </button>
        </div>
      </div>
    </dialog>,
    document.body,
  );
};
