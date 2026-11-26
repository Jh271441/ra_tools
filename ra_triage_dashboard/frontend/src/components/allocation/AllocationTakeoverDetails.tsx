import { useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { CASE_PAGE_SIZES, DEFAULT_CASE_PAGE_SIZE, Pagination } from "../ui/Pagination";
import { AllocationPreviewPlan, reviewAssignmentBatchHref, WorkSplitItem } from "./allocationMath";

const REASONS = {
  transfer: ["确认后转给你", "Transfers to you on confirmation"],
  mine: ["已在你的待办中", "Already assigned to you"],
  label_pending: ["模型复核已提交，Case 标签待确认", "Model review submitted, case label pending"],
  adjudicated: ["已有裁决，保留负责人", "Adjudicated, current owner retained"],
  saved: ["已有保存记录，保留负责人", "Saved work, current owner retained"],
  other_slot: ["你已参与此案例的复核", "You already have a review on this case"],
  pairing: ["保留该案例的分组或结对", "Existing group or pairing retained"],
} as const;

interface Props {
  preview: AllocationPreviewPlan;
  task?: WorkSplitItem;
  lang: UiLanguage;
  onNavigate: () => void;
}

export function AllocationTakeoverDetails({ preview, task, lang, onNavigate }: Props) {
  const rows = preview.remaining_assignments || [];
  const [pagination, setPagination] = useState<{ page: number; size: number }>(() => {
    const params = new URLSearchParams(window.location.search);
    const page = Number(params.get("transfer_page"));
    const size = Number(params.get("transfer_page_size"));
    return {
      page: Number.isSafeInteger(page) && page > 0 ? page : 1,
      size: CASE_PAGE_SIZES.find((value) => value === size) ?? DEFAULT_CASE_PAGE_SIZE,
    };
  });
  const page = Math.min(pagination.page, Math.max(1, Math.ceil(rows.length / pagination.size)));
  const start = (page - 1) * pagination.size;
  const updatePagination = (nextPage: number, size: number) => {
    setPagination({ page: nextPage, size });
    const url = new URL(window.location.href);
    url.searchParams.set("transfer_page", String(nextPage));
    url.searchParams.set("transfer_page_size", String(size));
    window.history.replaceState(window.history.state, "", url);
  };

  const moved = preview.moved_slots || 0;
  return (
    <section className="task-allocation-settings" aria-label={bilingual(lang, "接手预览", "Transfer preview")}>
      <h3 className="allocation-section-title">
        {moved
          ? bilingual(lang, `确认后接手 ${moved} 份待办`, `Take over ${moved} pending ${moved === 1 ? "assignment" : "assignments"} on confirmation`)
          : bilingual(lang, "没有可转给你的待办", "No pending assignments can be transferred to you")}
      </h3>
      {rows.length > 0 && (
        <ul className="ra-historical-batches">
          {rows.slice(start, start + pagination.size).map((row) => (
            <li className="ra-historical-batch-row" key={`${row.issue_id}/${row.owner}`}>
              <span>
                {task ? (
                  <a
                    className="ra-allocation-issue-link"
                    href={reviewAssignmentBatchHref(task, "review", "", false, {
                      issue: row.issue_id, taskProgress: [],
                    })}
                    onClick={onNavigate}
                  >
                    {row.issue_id}
                  </a>
                ) : <strong>{row.issue_id}</strong>}
                {" · "}{row.owner}
              </span>
              <small>{bilingual(lang, REASONS[row.reason][0], REASONS[row.reason][1])}</small>
            </li>
          ))}
        </ul>
      )}
      {rows.length > Math.min(DEFAULT_CASE_PAGE_SIZE, pagination.size) && (
        <Pagination
          lang={lang}
          page={page}
          pageSize={pagination.size}
          total={rows.length}
          ariaLabel={bilingual(lang, "接手预览分页", "Transfer preview pagination")}
          summaryText={bilingual(lang, `共 ${rows.length} 份待办`, `${rows.length} pending assignments`)}
          onPageChange={(value) => updatePagination(value, pagination.size)}
          onPageSizeChange={(size) => updatePagination(1, size)}
        />
      )}
    </section>
  );
}
