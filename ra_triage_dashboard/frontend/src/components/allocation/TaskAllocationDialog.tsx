import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiRequest } from "../../api/client";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { showWorkbenchToast } from "../ui/Toast";
import { UiSelect, UiSelectOption } from "../ui/UiSelect";
import { AllocationGroupSetup } from "./AllocationGroupSetup";
import { AllocationLivePreview, LegacyAllocationResults } from "./AllocationLivePreview";
import { AllocationTakeoverDetails } from "./AllocationTakeoverDetails";
import {
  AllocationConfig,
  AllocationDraft,
  AllocationPreviewPlan,
  BilingualMessage,
  WorkSplitItem,
  currentAllocationGroups,
  groupAllocationSetupError,
  i18nLocaleTag,
  newAllocationGroup,
  parseBilingualError,
  pendingReviewHref,
  taskAllocationGroupCompleted,
} from "./allocationMath";

export interface TaskAllocationDialogProps {
  campaignId: string | null;
  lang: UiLanguage;
  task?: WorkSplitItem;
  onClose: () => void;
  onSaved: () => void;
}

function buildDraftFromConfig(config: AllocationConfig): AllocationDraft {
  const basis = config.quota_basis === "total" ? "total" : "remaining";
  const groups = config.groups?.length ? currentAllocationGroups(config, basis) : [newAllocationGroup()];
  const rules = (config.group_rules || []).map((r) => ({
    members: (r.members || []).map((m) => ({ ...m })),
    issue_ids: [...(r.issue_ids || [])],
    count: r.count ?? null,
  }));
  const pairingMode: "orthogonal" | "paired" | "custom" = rules.length
    ? "custom"
    : config.pairing_mode === "paired"
      ? "paired"
      : "orthogonal";
  return {
    groups,
    cross_groups: rules,
    pairing_mode: pairingMode,
    ruleScopes: rules.map((r) => (r.issue_ids?.length ? "cases" : "count")),
    inputUnit: "percent",
    quota_basis: basis,
  };
}

function buildRequestBody(draft: AllocationDraft, config: AllocationConfig, takeOver = false) {
  if (takeOver) {
    return {
      takeover_pending: true,
      expected_revision: config.expected_revision,
      quota_basis: config.quota_basis || "remaining",
    };
  }
  return {
    groups: draft.groups,
    cross_groups: draft.pairing_mode === "custom" ? draft.cross_groups : [],
    pairing_mode: draft.pairing_mode === "paired" ? "paired" : "orthogonal",
    quota_basis: draft.quota_basis || "remaining",
    expected_revision: config.expected_revision,
  };
}

export function TaskAllocationDialog(props: TaskAllocationDialogProps) {
  const { campaignId } = props;
  return campaignId
    ? <TaskAllocationSession key={campaignId} {...props} campaignId={campaignId} />
    : null;
}

const TaskAllocationSession: React.FC<TaskAllocationDialogProps & { campaignId: string }> = ({
  campaignId,
  lang,
  task,
  onClose,
  onSaved,
}) => {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const previewHeadingRef = useRef<HTMLHeadingElement | null>(null);

  const [config, setConfig] = useState<AllocationConfig | null>(null);
  const [draft, setDraft] = useState<AllocationDraft | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<BilingualMessage | null>(null);

  const [preview, setPreview] = useState<AllocationPreviewPlan | null>(null);
  const [displayPreview, setDisplayPreview] = useState<AllocationPreviewPlan | null>(null);
  const [liveError, setLiveError] = useState<BilingualMessage | null>(null);
  const [liveFailed, setLiveFailed] = useState(false);
  const [previewPending, setPreviewPending] = useState(false);
  const [takeOver, setTakeOver] = useState(false);

  const [removal, setRemoval] = useState<"" | "all" | "member">("");
  const [removeAssignee, setRemoveAssignee] = useState("");
  const [removalBasis, setRemovalBasis] = useState<"remaining" | "total">("remaining");
  const [removalPreview, setRemovalPreview] = useState<AllocationPreviewPlan | null>(null);

  const liveSerializedRef = useRef<string>("");
  const initialRequestRef = useRef<string>("");
  const liveTimerRef = useRef<number | null>(null);
  const liveAbortRef = useRef<AbortController | null>(null);
  const idempotencyRef = useRef<{ serialized: string; key: string } | null>(null);
  const loadSeqRef = useRef(0);

  const cancelLivePreview = useCallback(() => {
    if (liveTimerRef.current) {
      window.clearTimeout(liveTimerRef.current);
      liveTimerRef.current = null;
    }
    liveAbortRef.current?.abort();
    liveAbortRef.current = null;
  }, []);

  const loadAllocationConfig = useCallback(
    async (targetId: string, preserveDraft?: AllocationDraft | null) => {
      const seq = ++loadSeqRef.current;
      cancelLivePreview();
      setLoadingConfig(true);
      setFormError(null);
      setPreview(null);
      setDisplayPreview(null);
      setPreviewPending(false);
      setLiveError(null);
      setLiveFailed(false);
      liveSerializedRef.current = "";
      try {
        const cfg = await apiRequest<AllocationConfig>(
          `/api/campaigns/${encodeURIComponent(targetId)}/allocation`,
        );
        if (seq !== loadSeqRef.current) return;
        const startingDraft = buildDraftFromConfig(cfg);
        initialRequestRef.current = JSON.stringify(buildRequestBody(startingDraft, cfg));
        setConfig(cfg);
        setDraft(preserveDraft || startingDraft);
        setRemovalBasis(cfg.quota_basis === "total" ? "total" : "remaining");
        if (!cfg.editable) {
          setFormError({
            zh: "此任务已结束，无法修改分配。",
            en: "This task is no longer active.",
          });
        }
      } catch (error) {
        if (seq !== loadSeqRef.current) return;
        setConfig(null);
        setFormError(
          parseBilingualError(
            error,
            "加载分配失败，请重试。",
            "Loading the allocation failed. Please retry.",
          ),
        );
      } finally {
        if (seq === loadSeqRef.current) setLoadingConfig(false);
      }
    },
    [cancelLivePreview],
  );

  useEffect(() => {
    setRemoveAssignee("");
    const el = dialogRef.current;
    if (el && !el.open) {
      if (typeof el.showModal === "function") el.showModal();
      else el.setAttribute("open", "");
    }
    void loadAllocationConfig(campaignId);
    return () => {
      loadSeqRef.current += 1;
      cancelLivePreview();
    };
  }, [campaignId, loadAllocationConfig, cancelLivePreview]);

  const executePreviewFetch = useCallback(
    async (targetId: string, bodyObj: ReturnType<typeof buildRequestBody>, serialized: string) => {
      cancelLivePreview();
      const controller = new AbortController();
      liveAbortRef.current = controller;
      const timeout = window.setTimeout(() => controller.abort(), 20000);
      setPreviewPending(true);
      setLiveError(null);
      setLiveFailed(false);
      try {
        const result = await apiRequest<AllocationPreviewPlan>(
          `/api/campaigns/${encodeURIComponent(targetId)}/allocation/preview`,
          {
            method: "POST",
            body: bodyObj,
            signal: controller.signal,
          },
        );
        if (liveSerializedRef.current !== serialized || liveAbortRef.current !== controller) return;
        setPreview(result);
        setDisplayPreview(result);
        setPreviewPending(false);
      } catch (error) {
        if (liveSerializedRef.current !== serialized || liveAbortRef.current !== controller) return;
        const errStatus = (error as { status?: number })?.status;
        setLiveFailed(errStatus !== 400);
        setLiveError(
          parseBilingualError(
            error,
            "暂时无法计算预览，请重试。",
            "The preview could not be calculated. Try again.",
          ),
        );
        setPreviewPending(false);
      } finally {
        window.clearTimeout(timeout);
      }
    },
    [cancelLivePreview],
  );

  const schedulePreview = useCallback(
    (nextDraft: AllocationDraft, cfg: AllocationConfig, immediate: boolean, transfer = false) => {
      if (!cfg.editable || busy || removal) return;
      const bodyObj = buildRequestBody(nextDraft, cfg, transfer);
      const serialized = JSON.stringify(bodyObj);
      if (serialized === liveSerializedRef.current) {
        if (immediate && liveTimerRef.current) {
          window.clearTimeout(liveTimerRef.current);
          liveTimerRef.current = null;
          void executePreviewFetch(cfg.campaign_id, bodyObj, serialized);
        }
        return;
      }
      cancelLivePreview();
      liveSerializedRef.current = serialized;
      setPreview(null);
      setFormError(null);
      if (serialized === initialRequestRef.current) {
        setDisplayPreview(null);
        setLiveError(null);
        setLiveFailed(false);
        setPreviewPending(false);
        return;
      }
      const validationErr = transfer ? null : groupAllocationSetupError(nextDraft);
      if (validationErr) {
        setLiveError(validationErr);
        setLiveFailed(false);
        setPreviewPending(false);
        return;
      }
      setLiveError(null);
      setLiveFailed(false);
      setPreviewPending(true);
      if (immediate) {
        void executePreviewFetch(cfg.campaign_id, bodyObj, serialized);
      } else {
        liveTimerRef.current = window.setTimeout(() => {
          liveTimerRef.current = null;
          void executePreviewFetch(cfg.campaign_id, bodyObj, serialized);
        }, 120);
      }
    },
    [busy, removal, cancelLivePreview, executePreviewFetch],
  );

  // Reloads may retain an edited draft. An untouched draft displays the saved assignment.
  useEffect(() => {
    if (!campaignId || !config || !draft || removal || loadingConfig) return;
    if (!liveSerializedRef.current && config.editable) {
      schedulePreview(draft, config, true, takeOver);
    }
  }, [campaignId, config, draft, removal, loadingConfig, takeOver, schedulePreview]);

  const handleClose = useCallback(() => {
    if (busy) return;
    cancelLivePreview();
    if (dialogRef.current?.open && typeof dialogRef.current.close === "function") {
      dialogRef.current.close();
    }
    onClose();
  }, [busy, cancelLivePreview, onClose]);

  const handleDraftChange = (nextDraft: AllocationDraft, meta: { immediate: boolean }) => {
    setDraft(nextDraft);
    if (config) schedulePreview(nextDraft, config, meta.immediate);
  };

  const handleFlush = () => {
    if (config && draft && liveTimerRef.current) {
      schedulePreview(draft, config, true);
    }
  };

  const handleBasisChange = (nextBasis: "remaining" | "total") => {
    if (!draft || !config) return;
    const nextDraft: AllocationDraft = { ...draft, quota_basis: nextBasis };
    setDraft(nextDraft);
    schedulePreview(nextDraft, config, true);
  };

  const handleUnitClick = (targetUnit: "percent" | "count") => {
    if (!draft || !config) return;
    const caseCount = Number(config.member_count || 0);
    const resolved: "percent" | "count" = targetUnit === "count" && caseCount > 0 ? "count" : "percent";
    if (resolved === draft.inputUnit) return;
    const nextDraft: AllocationDraft = { ...draft, inputUnit: resolved };
    setDraft(nextDraft);
  };

  const handleAddGroup = () => {
    if (!draft || !config || !config.editable) return;
    const nextDraft: AllocationDraft = {
      ...draft,
      groups: [...draft.groups, newAllocationGroup(draft.groups)],
    };
    setDraft(nextDraft);
    schedulePreview(nextDraft, config, true);
  };

  const toggleTakeOver = () => {
    if (!config || !draft) return;
    setTakeOver(!takeOver);
    setDisplayPreview(null);
    schedulePreview(draft, config, true, !takeOver);
  };

  const handleApply = async () => {
    if (!config?.editable || !draft || busy) return;
    const bodyObj = buildRequestBody(draft, config, takeOver);
    const serialized = JSON.stringify(bodyObj);
    if (
      !preview ||
      liveSerializedRef.current !== serialized ||
      (preview.expires_at && preview.expires_at * 1000 <= Date.now())
    ) {
      liveSerializedRef.current = "";
      schedulePreview(draft, config, true, takeOver);
      return;
    }
    const patchBody = { ...bodyObj, preview_token: preview.preview_token };
    const patchSerialized = JSON.stringify(patchBody);
    if (idempotencyRef.current?.serialized !== patchSerialized) {
      idempotencyRef.current = {
        serialized: patchSerialized,
        key:
          typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
            ? crypto.randomUUID()
            : `alloc-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      };
    }
    setBusy(true);
    setFormError(null);
    try {
      const result = await apiRequest<{ changed?: boolean }>(
        `/api/campaigns/${encodeURIComponent(config.campaign_id)}/allocation`,
        {
          method: "PATCH",
          headers: { "Idempotency-Key": idempotencyRef.current.key },
          body: patchBody,
        },
      );
      setBusy(false);
      showWorkbenchToast(
        result?.changed
          ? bilingual(
              lang,
              "分配已更新，已保存工作的内容和归属均已保留。",
              "Allocation updated. Saved work and ownership were preserved.",
            )
          : bilingual(lang, "分配没有变化，已保留原任务。", "No allocation changes. The task was retained."),
      );
      handleClose();
      onSaved();
    } catch (error) {
      const err = error as { status?: number; message?: string; messages?: BilingualMessage };
      const stale = err.status === 409;
      if (stale) {
        setPreview(null);
        setDisplayPreview(null);
        liveSerializedRef.current = "";
        await loadAllocationConfig(config.campaign_id, draft);
      }
      setFormError(
        stale
          ? {
              zh: "标注、成员或任务已变化。请核对更新后的预览。",
              en: "Work, members or the task changed. Review the updated preview.",
            }
          : err.messages
            ? err.messages
            : err.status === 400
              ? parseBilingualError(
                  error,
                  "分配配置无效，请检查成员权限、个人比例或数量及交叉设置。",
                  "Invalid allocation. Check member access, personal shares or quotas and cross-review settings.",
                )
              : { zh: "保存失败，请重试。", en: "Saving failed. Please retry." },
      );
      setBusy(false);
    }
  };

  const handleRemovalSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!config?.editable || busy || !removal) return;
    const whole = removal === "all";
    const base = `/api/campaigns/${encodeURIComponent(config.campaign_id)}/allocation`;
    const path = whole ? base : `${base}/assignees/${encodeURIComponent(removeAssignee)}`;
    const previewing = !whole && !removalPreview;
    setBusy(true);
    setFormError(null);
    try {
      if (previewing) {
        const freshCfg = await apiRequest<AllocationConfig>(base);
        setConfig(freshCfg);
        const remPrev = await apiRequest<AllocationPreviewPlan>(`${path}/removal-preview`, {
          method: "POST",
          body: {
            expected_revision: freshCfg.expected_revision,
            quota_basis: removalBasis,
          },
        });
        setRemovalPreview(remPrev);
        setBusy(false);
        return;
      }
      const delBody = whole
        ? {
            expected_revision: config.expected_revision,
            reason: "Allocation deleted through task editor; saved evidence retained.",
          }
        : {
            expected_revision: config.expected_revision,
            quota_basis: removalBasis,
            preview_token: removalPreview?.preview_token,
          };
      const serialized = JSON.stringify(delBody);
      if (idempotencyRef.current?.serialized !== serialized) {
        idempotencyRef.current = {
          serialized,
          key:
            typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
              ? crypto.randomUUID()
              : `alloc-del-${Date.now()}`,
        };
      }
      await apiRequest(path, {
        method: "DELETE",
        headers: { "Idempotency-Key": idempotencyRef.current.key },
        body: delBody,
      });
      setBusy(false);
      showWorkbenchToast(
        whole
          ? bilingual(
              lang,
              "分配已删除，已有成果保留在历史任务中。",
              "Allocation deleted; evidence remains in task history.",
            )
          : bilingual(
              lang,
              "个人未开始分配已取消，其余待办已接续。",
              "Unstarted assignments removed and remaining work redistributed.",
            ),
      );
      handleClose();
      onSaved();
    } catch (error) {
      const err = error as { status?: number };
      if (err.status === 409) setRemovalPreview(null);
      setFormError(
        err.status === 409
          ? {
              zh: "任务或标注已有变化，请重新核对分配。",
              en: "The task or saved work changed. Reload the allocation.",
            }
          : parseBilingualError(
              error,
              "操作失败。请检查剩余成员能否满足分配要求，再重试。",
              "The operation failed. Check that remaining members meet allocation requirements, then retry.",
            ),
      );
      setBusy(false);
    }
  };

  const numFmt = useMemo(() => new Intl.NumberFormat(i18nLocaleTag(lang)), [lang]);
  const groupCompleted = useMemo(() => taskAllocationGroupCompleted(config), [config]);

  const isWholeRemoval = removal === "all";
  const basisOptions: UiSelectOption[] = [
    {
      value: "remaining",
      label: bilingual(lang, "按剩余量分配", "Distribute remaining work"),
    },
    {
      value: "total",
      label: isWholeRemoval || removal === "member"
        ? bilingual(lang, "按全量均衡", "Balance total workload")
        : bilingual(lang, "按全量目标补齐", "Fill toward total targets"),
    },
  ];

  const shownPlan = preview || displayPreview || config;
  const hasChart = Boolean(shownPlan?.group_coverage?.case_count);
  const isUpdating = Boolean(previewPending && !liveError && config?.editable);
  const errorText = formError ? bilingual(lang, formError.zh, formError.en) : "";
  const liveStatusText = liveError
    ? bilingual(lang, liveError.zh, liveError.en)
    : isUpdating && !hasChart
      ? bilingual(lang, "正在计算预览…", "Calculating preview…")
      : "";
  const caseCount = Number(config?.member_count || 0);
  const pendingCount = Math.max(0, (config?.total_slots || 0) - (config?.completed_slots || 0));
  const canTakeOver = config?.editable && config.purpose === "model_review" && !config.role_required;
  const crossCoverage = (coverage: { cross_cases: number; case_count: number }) => {
    const percent = coverage.case_count ? coverage.cross_cases / coverage.case_count : 0;
    return `${numFmt.format(coverage.cross_cases)} / ${numFmt.format(coverage.case_count)} · ${new Intl.NumberFormat(
      i18nLocaleTag(lang), { style: "percent", maximumFractionDigits: 2 },
    ).format(percent)}`;
  };
  const currentUnit = draft?.inputUnit === "count" && caseCount > 0 ? "count" : "percent";
  const removedMember = config?.progress_members?.find((p) => p.name === removeAssignee);

  return createPortal(
    <dialog
      ref={dialogRef}
      id="raTaskAllocationDialog"
      className={`dialog task-allocation-dialog${config && !removal ? " is-allocation-edit" : ""}`}
      aria-labelledby="raTaskAllocationTitle"
      onCancel={(e) => {
        e.preventDefault();
        if (busy) return;
        if (removal) {
          setRemoval("");
          setFormError(null);
          setRemovalPreview(null);
          return;
        }
        handleClose();
      }}
    >
      {removal ? (
        <form className="dialog-card" onSubmit={(e) => void handleRemovalSubmit(e)}>
          <header className="dialog-header">
            <h2 id="raTaskAllocationTitle">
              {isWholeRemoval
                ? bilingual(lang, "删除整条任务分配", "Delete the whole allocation")
                : bilingual(lang, "取消个人未开始分配", "Remove unstarted assignments")}
            </h2>
            <button
              className="icon-button"
              type="button"
              disabled={busy}
              aria-label={bilingual(lang, "关闭", "Close")}
              onClick={handleClose}
            >
              ×
            </button>
          </header>

          {config ? (
            <>
              <p className="dialog-copy">{config.name || config.campaign_id}</p>
              <p className="task-allocation-note">
                {isWholeRemoval
                  ? bilingual(
                      lang,
                      `此任务将进入“已取消”，从当前分配中移除。已有 ${config.completed_slots || 0} 份完成记录和 ${config.saved_pending_slots || 0} 份已保存/保护待办全部保留，可从历史任务查看。取消后不能恢复为当前任务。`,
                      `This task will become Cancelled and leave current allocations. All ${config.completed_slots || 0} completed and ${config.saved_pending_slots || 0} saved/protected pending slots are retained in task history. Cancellation cannot be undone.`,
                    )
                  : bilingual(
                      lang,
                      `取消 ${removeAssignee} 的未开始分配。保留其 ${removedMember?.completed || 0} 份已完成和 ${removedMember?.saved_pending || 0} 份已保存/保护待办；未开始部分由其余成员接续。`,
                      `Remove ${removeAssignee} from unstarted assignments. Retain their ${removedMember?.completed || 0} completed and ${removedMember?.saved_pending || 0} saved/protected pending slots; other members will take the untouched work.`,
                    )}
              </p>
              {isWholeRemoval ? (
                <>
                  <p className="dialog-copy">
                    {bilingual(
                      lang,
                      "任务及成果保留在历史记录中，后续提交将被停止。",
                      "The task and its evidence remain in history; further submissions will stop.",
                    )}
                  </p>
                  {config.appendable && (
                    <p className="dialog-copy">
                      {bilingual(
                        lang,
                        "该任务为持续追加任务，取消后也将停止向其追加新 Case。",
                        "This is an appendable task. Cancellation also stops new Cases from being appended.",
                      )}
                    </p>
                  )}
                </>
              ) : (
                <>
                  <p className="dialog-copy">
                    {bilingual(
                      lang,
                      "使用已保存的成员比例，在剩余成员中归一为 100%。原分组数与交叉要求保持；人数不足时，请返回修改分配并先补充接收人。",
                      "Saved shares are normalized to 100% among the remaining members. Group counts and cross-review requirements stay fixed. If recipients are insufficient, go back and add a replacement first.",
                    )}
                  </p>
                  <div className="task-allocation-fields">
                    <div className="ra-alloc-field">
                      <span>{bilingual(lang, "分配基数", "Allocation basis")}</span>
                      <UiSelect
                        value={removalBasis}
                        options={basisOptions}
                        disabled={busy}
                        ariaLabel={bilingual(lang, "分配基数", "Allocation basis")}
                        onChange={(val) => {
                          setRemovalBasis(val === "total" ? "total" : "remaining");
                          setRemovalPreview(null);
                        }}
                      />
                    </div>
                  </div>
                </>
              )}
            </>
          ) : (
            <p className="dialog-copy">{bilingual(lang, "正在加载分配…", "Loading allocation…")}</p>
          )}

          {removalPreview && (
            <section
              id="taskAllocationPreview"
              className="task-allocation-preview"
              aria-label={bilingual(lang, "调整结果", "Allocation results")}
            >
              <LegacyAllocationResults preview={removalPreview} config={config} lang={lang} />
            </section>
          )}

          <p className="task-allocation-error" role="alert">
            {errorText}
          </p>

          <footer className="dialog-actions">
            <button
              type="button"
              className="button button-quiet"
              disabled={busy}
              onClick={() => {
                setRemoval("");
                setFormError(null);
                setRemovalPreview(null);
              }}
            >
              {bilingual(lang, "返回修改分配", "Back to editing")}
            </button>
            {formError && (
              <button
                type="button"
                className="button button-quiet"
                disabled={busy}
                onClick={() => void loadAllocationConfig(campaignId)}
              >
                {bilingual(lang, "重新核对分配", "Reload allocation")}
              </button>
            )}
            {!isWholeRemoval && (
              <button type="button" className="button button-quiet" disabled={busy} onClick={handleClose}>
                {bilingual(lang, "返回", "Go back")}
              </button>
            )}
            <button
              type="submit"
              className="button button-primary"
              disabled={busy || !config?.editable}
            >
              {busy
                ? bilingual(lang, "正在处理…", "Working…")
                : isWholeRemoval
                  ? bilingual(lang, "删除分配并保留成果", "Delete allocation, retain evidence")
                  : removalPreview
                    ? bilingual(lang, "确认取消并接续待办", "Confirm removal and redistribute")
                    : bilingual(lang, "预览调整", "Preview changes")}
            </button>
          </footer>
        </form>
      ) : (
        <form className="dialog-card" id="taskAllocationForm" onSubmit={(e) => e.preventDefault()}>
          <header className="dialog-header">
            <div className="task-allocation-heading">
              <h2 id="raTaskAllocationTitle" tabIndex={-1}>
                {bilingual(lang, "修改任务分配", "Edit task allocation")}
              </h2>
              {config && (
                <p className="dialog-copy">
                  {`${config.name || config.campaign_id} · ${bilingual(
                    lang,
                    "已完成与已保存记录自动保留",
                    "Completed and saved work stays locked",
                  )}`}
                </p>
              )}
            </div>
            <button
              className="icon-button"
              type="button"
              disabled={busy}
              aria-label={bilingual(lang, "关闭", "Close")}
              onClick={handleClose}
            >
              ×
            </button>
          </header>

          {config && draft ? (
            <div className="task-allocation-body">
              <div className="allocation-review-status">
                <div>
                  {config.coverage && (
                    <p className="dialog-copy">
                      {bilingual(lang, "当前交叉覆盖", "Current cross-review coverage")}{" "}
                      <strong>{crossCoverage(config.coverage)}</strong>
                      {preview?.coverage_after && <> {"→"} <strong>{crossCoverage(preview.coverage_after)}</strong></>}
                    </p>
                  )}
                  <p className="dialog-copy">
                    {pendingCount
                      ? bilingual(lang,
                          `待办 ${numFmt.format(pendingCount)} 份 · 可转派 ${numFmt.format(config.movable_slots || 0)} 份 · 受保护 ${numFmt.format(config.saved_pending_slots || 0)} 份`,
                          `${numFmt.format(pendingCount)} pending · ${numFmt.format(config.movable_slots || 0)} transferable · ${numFmt.format(config.saved_pending_slots || 0)} protected`)
                      : bilingual(lang, "已全部完成", "All assignments completed")}
                  </p>
                </div>
                <div className="review-assignment-batch-actions">
                  {task?.workflow_mode === "model_review_and_case_label" && pendingCount > 0 && (
                    <a className="button button-quiet" href={pendingReviewHref(task)} onClick={handleClose}>
                      {bilingual(lang, "查看全部剩余 Issue", "View all pending cases")}
                    </a>
                  )}
                  {canTakeOver && (pendingCount > 0 || takeOver) && (
                    <button className="button button-secondary" type="button" disabled={busy} onClick={toggleTakeOver}>
                      {takeOver
                        ? bilingual(lang, "返回分配设置", "Back to allocation settings")
                        : bilingual(lang, "将可转派待办分给我", "Assign movable work to me")}
                    </button>
                  )}
                </div>
              </div>
              {takeOver && preview && (
                <AllocationTakeoverDetails preview={preview} task={task} lang={lang} onNavigate={handleClose} />
              )}
              <div className="task-allocation-settings" hidden={takeOver}>
                <div className="allocation-basis-bar">
                  <div className="allocation-section-heading">
                    <h3 className="allocation-section-title">
                      {bilingual(lang, "分配组", "Allocation groups")}
                    </h3>
                  </div>

                  <div className="allocation-basis-controls">
                    <div
                      className="allocation-unit-switch"
                      role="group"
                      aria-label={bilingual(lang, "数值单位", "Input unit")}
                    >
                      <button
                        type="button"
                        data-allocation-unit="percent"
                        className={currentUnit !== "count" ? "is-active" : undefined}
                        aria-pressed={currentUnit !== "count"}
                        disabled={busy}
                        title={bilingual(lang, "按百分比输入", "Enter percentages")}
                        onClick={() => handleUnitClick("percent")}
                      >
                        %
                      </button>
                      <button
                        type="button"
                        data-allocation-unit="count"
                        className={currentUnit === "count" ? "is-active" : undefined}
                        aria-pressed={currentUnit === "count"}
                        disabled={busy || !(caseCount > 0)}
                        title={bilingual(lang, "按具体条数输入", "Enter exact case counts")}
                        onClick={() => handleUnitClick("count")}
                      >
                        {bilingual(lang, "条", "Count")}
                      </button>
                    </div>

                    <div className="allocation-basis-inline">
                      <span>{bilingual(lang, "分配基数", "Basis")}</span>
                      <UiSelect
                        id="taskAllocationBasis"
                        value={draft.quota_basis || "remaining"}
                        options={basisOptions}
                        disabled={busy || !config.editable}
                        ariaLabel={bilingual(lang, "分配基数", "Basis")}
                        onChange={(val) =>
                          handleBasisChange(val === "total" ? "total" : "remaining")
                        }
                      />
                    </div>

                    {config.editable && (
                      <button
                        className="button button-secondary allocation-compact-btn"
                        type="button"
                        disabled={busy}
                        onClick={handleAddGroup}
                      >
                        + {bilingual(lang, "添加分配组", "Add group")}
                      </button>
                    )}
                  </div>
                </div>

                <AllocationGroupSetup
                  id="taskAllocationGroupSetup"
                  draft={draft}
                  users={config.eligible_members || []}
                  lang={lang}
                  editable={Boolean(config.editable) && !busy}
                  caseCount={caseCount}
                  quotaBasis={draft.quota_basis || "remaining"}
                  groupCompleted={groupCompleted}
                  hideBar
                  onChange={handleDraftChange}
                  onFlush={handleFlush}
                />
              </div>

              <section
                id="taskAllocationPreview"
                className="task-allocation-preview"
                aria-labelledby="taskAllocationPreviewTitle"
              >
                <div className="allocation-preview-heading">
                  <h3 id="taskAllocationPreviewTitle" ref={previewHeadingRef} tabIndex={-1}>
                    {preview || displayPreview || previewPending
                      ? bilingual(lang, "实时预览", "Live preview")
                      : bilingual(lang, "当前分配 · 0 人变动", "Current allocation · No changes")}
                  </h3>
                  <span
                    className="allocation-preview-pending"
                    aria-live="polite"
                    hidden={!(isUpdating && hasChart)}
                  >
                    <i className="allocation-preview-spinner" aria-hidden="true" />
                    <span>{bilingual(lang, "更新中…", "Updating…")}</span>
                  </span>
                </div>
                <div
                  id="taskAllocationLiveContent"
                  className={`allocation-live-content${isUpdating && hasChart ? " is-preview-updating" : ""}${liveError && hasChart ? " is-preview-stale" : ""}`}
                >
                  <AllocationLivePreview
                    plan={shownPlan}
                    config={config}
                    configuredGroups={draft.groups}
                    lang={lang}
                    editing={Boolean(preview || displayPreview)}
                  />
                </div>
              </section>
            </div>
          ) : (
            <p className="dialog-copy">
              {loadingConfig
                ? bilingual(lang, "正在加载分配…", "Loading allocation…")
                : bilingual(lang, "未能加载分配配置。", "Could not load allocation.")}
            </p>
          )}

          {config && (
            <div className="allocation-live-status">
              <p
                className={`dialog-copy${liveError ? " task-allocation-error" : ""}`}
                role="status"
              >
                {liveStatusText}
              </p>
              <button
                className="button button-secondary"
                type="button"
                hidden={!liveFailed}
                disabled={busy}
                onClick={() => void loadAllocationConfig(campaignId, draft)}
              >
                {bilingual(lang, "重新计算", "Recalculate")}
              </button>
            </div>
          )}

          <p className="task-allocation-error" role="alert" id="taskAllocationError">
            {errorText}
          </p>

          <footer className="task-allocation-edit-footer">
            <div className="task-allocation-footer-start">
              {config && (
                <button
                  className="button button-secondary task-allocation-preview-jump"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    previewHeadingRef.current?.scrollIntoView?.({ block: "start" });
                    previewHeadingRef.current?.focus({ preventScroll: true });
                  }}
                >
                  {bilingual(lang, "查看图表", "View chart")}
                </button>
              )}
              {config?.editable && (
                <button
                  className="button button-quiet task-allocation-danger-btn"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setRemoval("all");
                    setFormError(null);
                    setRemovalPreview(null);
                  }}
                >
                  {bilingual(lang, "删除整条分配…", "Delete allocation…")}
                </button>
              )}
            </div>

            <div className="dialog-actions">
              <button
                className="button button-secondary"
                type="button"
                hidden={Boolean(config) || !formError}
                disabled={busy}
                onClick={() => void loadAllocationConfig(campaignId)}
              >
                {bilingual(lang, "重新加载分配", "Reload allocation")}
              </button>
              <button
                className="button button-secondary"
                type="button"
                disabled={busy}
                onClick={handleClose}
              >
                {bilingual(lang, "取消", "Cancel")}
              </button>
              <button
                className="button button-primary"
                type="button"
                id="taskAllocationSave"
                disabled={busy || !preview?.preview_token || !config?.editable || (takeOver && !preview.moved_slots)}
                onClick={() => void handleApply()}
              >
                {busy
                  ? bilingual(lang, "正在保存…", "Saving…")
                  : takeOver
                    ? bilingual(lang, "确认接手", "Confirm transfer")
                    : bilingual(lang, "应用调整", "Apply changes")}
              </button>
            </div>
          </footer>
        </form>
      )}
    </dialog>,
    document.body,
  );
};
