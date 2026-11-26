import React, { useMemo, useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";

export interface PromptMetaLike {
  source_type?: string | null;
  source?: string | null;
  version?: string | null;
  stage?: string | null;
  mode?: string | null;
  sha256?: string | null;
  computed_sha256?: string | null;
  hash_matches?: boolean | null;
  redacted?: boolean | null;
  example_case_id?: string | null;
  template?: string | null;
  text?: string | null;
}

export interface RunSnapshotLike {
  id?: string | null;
  name?: string | null;
  prompt?: PromptMetaLike | null;
  input?: {
    available?: boolean;
    profile?: string | null;
    config?: Record<string, unknown> | null;
  } | null;
  model?: {
    name?: string | null;
    resolved_id?: string | null;
    requested_id?: string | null;
  } | null;
}

export interface DiffRow {
  kind: "same" | "delete" | "add" | "change";
  a?: string;
  b?: string;
  i?: number;
  j?: number;
}

export function comparisonCanonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(comparisonCanonical);
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.keys(obj)
        .sort()
        .map((k) => [k, comparisonCanonical(obj[k])]),
    );
  }
  return value;
}

export function comparisonConfigText(value: unknown): string {
  return value == null ? "" : JSON.stringify(comparisonCanonical(value), null, 2);
}

/**
 * Bounded LCS diff (<= 200k total chars and <= 1M DP cells), matching classic run-comparison.js 1:1.
 */
export function computeComparisonDiffLines(left: string, right: string): DiffRow[] | null {
  const a = left.split("\n");
  const b = right.split("\n");
  if (left.length + right.length > 200_000 || a.length * b.length > 1_000_000) return null;
  const dp: Uint32Array[] = Array.from({ length: a.length + 1 }, () => new Uint32Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const raw: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      raw.push({ kind: "same", a: a[i], b: b[j], i: i + 1, j: j + 1 });
      i += 1;
      j += 1;
    } else if (i < a.length && (j === b.length || dp[i + 1][j] >= dp[i][j + 1])) {
      raw.push({ kind: "delete", a: a[i], i: i + 1 });
      i += 1;
    } else {
      raw.push({ kind: "add", b: b[j], j: j + 1 });
      j += 1;
    }
  }
  const aligned: DiffRow[] = [];
  for (let n = 0; n < raw.length; ) {
    if (raw[n].kind === "same") {
      aligned.push(raw[n]);
      n += 1;
      continue;
    }
    const removed: DiffRow[] = [];
    const added: DiffRow[] = [];
    while (n < raw.length && raw[n].kind !== "same") {
      const r = raw[n];
      n += 1;
      if (r.kind === "delete") removed.push(r);
      else added.push(r);
    }
    const count = Math.max(removed.length, added.length);
    for (let k = 0; k < count; k += 1) {
      const del = removed[k];
      const add = added[k];
      aligned.push({
        a: del?.a,
        i: del?.i,
        b: add?.b,
        j: add?.j,
        kind: del && add ? "change" : del ? "delete" : "add",
      });
    }
  }
  return aligned;
}

function renderInlineHighlight(text: string | undefined, peer: string | undefined): React.ReactNode {
  if (text == null) return "";
  if (peer == null) return text;
  let start = 0;
  let end = 0;
  const minLen = Math.min(text.length, peer.length);
  while (start < minLen && text[start] === peer[start]) start += 1;
  while (end < minLen - start && text[text.length - end - 1] === peer[peer.length - end - 1]) {
    end += 1;
  }
  const prefix = text.slice(0, start);
  const middle = text.slice(start, text.length - end);
  const suffix = end ? text.slice(-end) : "";
  return (
    <>
      {prefix}
      <mark>{middle}</mark>
      {suffix}
    </>
  );
}

export const PromptMetaBadge: React.FC<{ prompt?: PromptMetaLike | null; lang: UiLanguage }> = ({
  prompt,
  lang,
}) => {
  const types: Record<string, string> = {
    actual_input: bilingual(lang, "实际输入", "Actual input"),
    run_example: bilingual(lang, "Run 示例", "Run example"),
    run_template: bilingual(lang, "Run 模板", "Run template"),
    not_saved: bilingual(lang, "未保存", "Not saved"),
  };
  const badge = types[String(prompt?.source_type || "")] || bilingual(lang, "未保存", "Not saved");
  const hash = String(prompt?.sha256 || prompt?.computed_sha256 || "");
  const details = [
    prompt?.source,
    prompt?.version,
    prompt?.stage,
    hash,
    prompt?.hash_matches === false
      ? bilingual(lang, "保存哈希与文本不一致", "Saved hash differs from text")
      : "",
    prompt?.redacted ? bilingual(lang, "展示内容已脱敏", "Content redacted") : "",
  ].filter(Boolean) as string[];

  return (
    <>
      <span className="prompt-source-badge">{badge}</span>
      {prompt?.example_case_id ? (
        <span className="prompt-example">
          {bilingual(lang, "示例 Case: ", "Example Case: ")}
          {prompt.example_case_id}
        </span>
      ) : null}
      <details className="prompt-provenance">
        <summary>
          {hash ? `SHA ${hash.slice(0, 12)}` : bilingual(lang, "来源信息", "Provenance")}
        </summary>
        <div>
          {details.length
            ? details.map((line, idx) => (
                <React.Fragment key={idx}>
                  {idx > 0 ? <br /> : null}
                  {line}
                </React.Fragment>
              ))
            : bilingual(lang, "未保存", "Not saved")}
        </div>
      </details>
    </>
  );
};

export const RunSnapshotView: React.FC<{ run?: RunSnapshotLike | null; lang: UiLanguage }> = ({
  run,
  lang,
}) => {
  const prompt = run?.prompt || {};
  const input = run?.input || {};
  const model = run?.model || {};
  const promptMeta = [
    prompt.version,
    prompt.mode,
    prompt.sha256 ? prompt.sha256.slice(0, 12) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const inputJson =
    input.config && Object.keys(input.config).length
      ? JSON.stringify(input.config, null, 2)
      : "";

  return (
    <>
      <div className="comparison-snapshot-meta">
        <span>
          <strong>Run</strong> {run?.name || run?.id || "—"}
        </span>
        <span>
          <strong>Model</strong> {model.name || model.resolved_id || model.requested_id || "—"}
        </span>
        <span>
          <strong>Input profile</strong> {input.profile || "—"}
        </span>
      </div>
      <h4>
        Prompt {promptMeta ? <small>{promptMeta}</small> : null}
      </h4>
      {prompt.template ? (
        <pre>{prompt.template}</pre>
      ) : (
        <p className="muted">
          {bilingual(
            lang,
            "该 Run 没有保存 Prompt 快照。",
            "No Prompt snapshot was saved for this Run.",
          )}
        </p>
      )}
      <h4>{bilingual(lang, "输入配置", "Input configuration")}</h4>
      {inputJson ? (
        <pre>{inputJson}</pre>
      ) : (
        <p className="muted">
          {bilingual(
            lang,
            "该 Run 没有保存输入配置快照。",
            "No input snapshot was saved for this Run.",
          )}
        </p>
      )}
    </>
  );
};

export const ComparisonDiffView: React.FC<{
  left: string;
  right: string;
  lang: UiLanguage;
}> = ({ left, right, lang }) => {
  const [full, setFull] = useState(false);
  const [unified, setUnified] = useState(false);

  const safeLeft = String(left || "");
  const safeRight = String(right || "");
  const rows = useMemo(
    () => computeComparisonDiffLines(safeLeft, safeRight),
    [safeLeft, safeRight],
  );

  const notice = !safeLeft && !safeRight
    ? bilingual(lang, "两侧均未保存", "Neither side saved")
    : !safeLeft
      ? bilingual(lang, "基线未保存", "Baseline not saved")
      : !safeRight
        ? bilingual(lang, "新 Run 未保存", "Candidate Run not saved")
        : safeLeft === safeRight
          ? bilingual(lang, "内容一致", "Identical content")
          : "";

  const renderRow = (r: DiffRow, key: string) => {
    const aContent = r.kind === "change" ? renderInlineHighlight(r.a, r.b) : r.a || "";
    const bContent = r.kind === "change" ? renderInlineHighlight(r.b, r.a) : r.b || "";
    if (unified) {
      if (r.kind === "same") {
        return (
          <div className="diff-line same" key={key}>
            <small>
              {r.i} / {r.j}
            </small>
            <code> {aContent}</code>
          </div>
        );
      }
      return (
        <React.Fragment key={key}>
          {r.a != null ? (
            <div className="diff-line delete">
              <small>{r.i}</small>
              <code>− {aContent}</code>
            </div>
          ) : null}
          {r.b != null ? (
            <div className="diff-line add">
              <small>{r.j}</small>
              <code>+ {bContent}</code>
            </div>
          ) : null}
        </React.Fragment>
      );
    }
    return (
      <div className="diff-pair" key={key}>
        <div className={`diff-line ${r.a == null ? "empty" : r.kind === "same" ? "same" : "delete"}`}>
          <small>{r.i || ""}</small>
          <code>{aContent}</code>
        </div>
        <div className={`diff-line ${r.b == null ? "empty" : r.kind === "same" ? "same" : "add"}`}>
          <small>{r.j || ""}</small>
          <code>{bContent}</code>
        </div>
      </div>
    );
  };

  const renderedBlocks = useMemo(() => {
    if (!rows || full) return null;
    const blocks: React.ReactNode[] = [];
    for (let n = 0; n < rows.length; ) {
      if (rows[n].kind !== "same") {
        blocks.push(renderRow(rows[n], `r-${n}`));
        n += 1;
        continue;
      }
      const start = n;
      while (n < rows.length && rows[n].kind === "same") n += 1;
      const group = rows.slice(start, n);
      if (group.length > 8) {
        group.slice(0, 3).forEach((item, idx) => blocks.push(renderRow(item, `s-${start}-${idx}`)));
        blocks.push(
          <details className="diff-fold" key={`fold-${start}`}>
            <summary>
              {bilingual(
                lang,
                `展开 ${group.length - 6} 行相同内容`,
                `Expand ${group.length - 6} unchanged lines`,
              )}
            </summary>
            {group
              .slice(3, -3)
              .map((item, idx) => renderRow(item, `f-${start}-${idx}`))}
          </details>,
        );
        group
          .slice(-3)
          .forEach((item, idx) => blocks.push(renderRow(item, `e-${start}-${idx}`)));
      } else {
        group.forEach((item, idx) => blocks.push(renderRow(item, `g-${start}-${idx}`)));
      }
    }
    return blocks;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, full, unified, lang]);

  return (
    <>
      <div className="comparison-diff-controls">
        <label>
          <input
            type="checkbox"
            checked={full}
            onChange={(e) => setFull(e.target.checked)}
          />{" "}
          {bilingual(lang, "完整原文", "Full text")}
        </label>
        <label>
          <input
            type="checkbox"
            checked={unified}
            onChange={(e) => setUnified(e.target.checked)}
          />{" "}
          {bilingual(lang, "统一视图", "Unified view")}
        </label>
      </div>
      <div className="comparison-diff-body">
        {!rows || full ? (
          <>
            <p className="diff-notice">
              {notice}{" "}
              {!rows
                ? bilingual(
                    lang,
                    "文本超出差异计算上限，已降级为原文。",
                    "Text exceeded diff limit; falling back to raw text.",
                  )
                : ""}
            </p>
            <div className="comparison-original">
              <pre>{safeLeft || bilingual(lang, "未保存", "Not saved")}</pre>
              <pre>{safeRight || bilingual(lang, "未保存", "Not saved")}</pre>
            </div>
          </>
        ) : (
          <>
            {notice ? <p className="diff-notice">{notice}</p> : null}
            <div className="diff-head">
              <span>{bilingual(lang, "基线", "Baseline")}</span>
              <span>{bilingual(lang, "新 Run", "Candidate")}</span>
            </div>
            {renderedBlocks}
          </>
        )}
      </div>
    </>
  );
};
