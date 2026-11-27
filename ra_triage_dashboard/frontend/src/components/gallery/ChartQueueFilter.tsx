import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";

const gtLabels = {
  ready: ["GT 待更新", "GT update needed"],
  blocked: ["需确认", "Needs confirmation"],
  aligned: ["与 GT 一致", "Matches GT"],
} as const;
const reviewLabels = {
  pending: ["待开始", "Not started"],
  in_progress: ["待复核", "Awaiting review"],
  completed: ["已完成", "Completed"],
} as const;
const labelStates = {
  resolved: ["已形成结论", "Resolved"],
  pending: ["待形成结论", "Pending conclusion"],
  conflict: ["待裁决 / 需确认", "Needs adjudication / confirmation"],
} as const;

export function ChartQueueFilter({ lang, gt, review, label, onClear }: {
  lang: UiLanguage; gt?: string | null; review?: string | null; label?: string | null; onClear: () => void;
}) {
  const names = [gtLabels[gt as keyof typeof gtLabels], reviewLabels[review as keyof typeof reviewLabels],
    labelStates[label as keyof typeof labelStates]].filter(Boolean);
  if (!names.length) return null;
  return <div className="chart-queue-filter">
    <span>{names.map(pair => pair[lang === "en" ? 1 : 0]).join(" · ")}</span>
    <button type="button" className="text-link" onClick={onClear}>
      {bilingual(lang, "清除图表筛选", "Clear chart filter")}
    </button>
  </div>;
}
