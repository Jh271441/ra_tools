import { bilingual, UiLanguage, withWorkbenchBase } from "../../bridge/useWorkbenchBridge";

interface HistoryGroup {
  kind: "original" | "comparison" | "label_only";
  run_id: string;
  run_name: string;
  issue_ids: string[];
}

export interface LabelHistoryCollection {
  version: string;
  issue_ids: string[];
  groups: HistoryGroup[];
}

export function LabelHistoryCard({ collection, lang }: { collection: LabelHistoryCollection; lang: UiLanguage }) {
  const titles = {
    original: bilingual(lang, "原 Run", "Original Run"),
    comparison: bilingual(lang, "其他 Run 可对照", "Compare another Run"),
    label_only: bilingual(lang, "仅标注", "Label only"),
  };
  function link(issueIds: string[], title: string, runId = "") {
    const params = new URLSearchParams({ baselines: collection.version, issue_ids: issueIds.join(",") });
    if (runId) {
      params.set("run", runId);
      params.set("comparison", "all");
    }
    const path = withWorkbenchBase(runId ? "/review-analysis" : "/case-labeling");
    return <a key={title + runId} className="button button-quiet" href={path + "?" + params}>{title} ({issueIds.length})</a>;
  }
  return <article className="review-assignment-batch label-history-card">
    <strong className="review-assignment-batch-title">{collection.version} · {bilingual(lang, "历史联合复核", "Historical combined review")}</strong>
    <div className="review-assignment-batch-actions">
      {link(collection.issue_ids, bilingual(lang, "全部标注", "All annotations"))}
      {collection.groups.map(group => link(group.issue_ids, [titles[group.kind], group.run_name].filter(Boolean).join(" · "), group.run_id))}
    </div>
  </article>;
}
