import React, { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { apiRequest } from "../../api/client";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { ModalDialog } from "../../components/ui/ModalDialog";
import { UiSelect } from "../../components/ui/UiSelect";
import { AllocationPreviewPanel, AllocationPreviewPayload } from "./AllocationPreviewPanel";
import { GroupShareEditor } from "./GroupShareEditor";
import {
  AllocationGroup,
  createNewAllocationGroup,
  InputUnit,
  PairingMode,
  QuotaBasis,
  validateAllocationGroups,
} from "./rebalance";

export interface CampaignAllocationConfig {
  campaign_id: string;
  name?: string;
  editable: boolean;
  expected_revision: number;
  member_count: number;
  movable_slots: number;
  completed_slots: number;
  saved_pending_slots: number;
  quota_basis?: QuotaBasis;
  pairing_mode?: PairingMode;
  eligible_members: string[];
  groups: AllocationGroup[];
  group_coverage?: AllocationPreviewPayload["group_coverage"];
}

export interface AllocationEditorModalProps {
  campaignId: string | null;
  lang: UiLanguage;
  onClose: () => void;
  onSaved: () => void;
}

export const AllocationEditorModal: React.FC<AllocationEditorModalProps> = ({
  campaignId,
  lang,
  onClose,
  onSaved,
}) => {
  const open = Boolean(campaignId);
  const [groups, setGroups] = useState<AllocationGroup[]>([]);
  const [unit, setUnit] = useState<InputUnit>("percent");
  const [quotaBasis, setQuotaBasis] = useState<QuotaBasis>("remaining");
  const [pairingMode, setPairingMode] = useState<PairingMode>("orthogonal");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [debouncedBody, setDebouncedBody] = useState<string>("");
  const timerRef = useRef<number | null>(null);

  const configQuery = useQuery<CampaignAllocationConfig>({
    queryKey: ["campaign-allocation", campaignId],
    queryFn: ({ signal }) =>
      apiRequest<CampaignAllocationConfig>(
        `/api/campaigns/${encodeURIComponent(campaignId || "")}/allocation`,
        { signal },
      ),
    enabled: open,
    staleTime: 0,
  });

  useEffect(() => {
    if (!configQuery.data) return;
    const cfg = configQuery.data;
    const hydrated: AllocationGroup[] = (cfg.groups || []).map((g) => ({
      group_id: g.group_id,
      coverage_percent: Number(g.coverage_percent ?? 100),
      coverage_strategy: g.coverage_strategy || "overlap",
      members: (g.members || []).map((m) => ({
        name: String(m.name || ""),
        review_percent: Number(m.review_percent ?? 0),
      })),
      pinnedIndices: [],
    }));
    setGroups(hydrated.length ? hydrated : [createNewAllocationGroup([])]);
    setQuotaBasis(cfg.quota_basis === "total" ? "total" : "remaining");
    setPairingMode(cfg.pairing_mode === "paired" ? "paired" : "orthogonal");
    setConfirmDelete(false);
    setActionError(null);
  }, [configQuery.data]);

  const validationError = useMemo(
    () => (groups.length ? validateAllocationGroups(groups, lang) : null),
    [groups, lang],
  );

  const requestPayload = useMemo(() => {
    const cfg = configQuery.data;
    if (!cfg || !groups.length) return null;
    return {
      groups: groups.map((g) => ({
        group_id: g.group_id,
        coverage_percent: g.coverage_percent,
        coverage_strategy: g.coverage_strategy || "overlap",
        members: g.members.filter((m) => m.name.trim()).map((m) => ({
          name: m.name,
          review_percent: m.review_percent,
        })),
      })),
      cross_groups: [],
      pairing_mode: pairingMode,
      quota_basis: quotaBasis,
      expected_revision: cfg.expected_revision,
    };
  }, [configQuery.data, groups, pairingMode, quotaBasis]);

  const serializedPayload = useMemo(
    () => (requestPayload && !validationError ? JSON.stringify(requestPayload) : ""),
    [requestPayload, validationError],
  );

  const schedulePreview = (serialized: string, immediate: boolean) => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (!serialized) {
      setDebouncedBody("");
      return;
    }
    if (immediate) {
      setDebouncedBody(serialized);
    } else {
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        setDebouncedBody(serialized);
      }, 120);
    }
  };

  useEffect(() => {
    schedulePreview(serializedPayload, !debouncedBody);
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serializedPayload]);

  const previewQuery = useQuery<AllocationPreviewPayload>({
    queryKey: ["campaign-allocation-preview", campaignId, debouncedBody],
    queryFn: ({ signal }) =>
      apiRequest<AllocationPreviewPayload>(
        `/api/campaigns/${encodeURIComponent(campaignId || "")}/allocation/preview`,
        { method: "POST", body: JSON.parse(debouncedBody), signal },
      ),
    enabled: open && Boolean(configQuery.data?.editable) && Boolean(debouncedBody) && !confirmDelete,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 10_000,
  });

  const applyMutation = useMutation({
    mutationFn: () => {
      const cfg = configQuery.data;
      const preview = previewQuery.data;
      if (!cfg || !requestPayload || !preview?.preview_token) {
        throw new Error(bilingual(lang, "请先等待预览计算完成。", "Wait for live preview first."));
      }
      const key =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `alloc-${Date.now()}`;
      return apiRequest(`/api/campaigns/${encodeURIComponent(cfg.campaign_id)}/allocation`, {
        method: "PATCH",
        headers: { "Idempotency-Key": key },
        body: { ...requestPayload, preview_token: preview.preview_token },
      });
    },
    onSuccess: () => {
      setActionError(null);
      onSaved();
      onClose();
    },
    onError: (err) => {
      setActionError(
        err instanceof Error ? err.message : bilingual(lang, "保存失败，请重试。", "Save failed."),
      );
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => {
      const cfg = configQuery.data;
      if (!cfg) throw new Error("Missing allocation config");
      const key =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `alloc-del-${Date.now()}`;
      return apiRequest(`/api/campaigns/${encodeURIComponent(cfg.campaign_id)}/allocation`, {
        method: "DELETE",
        headers: { "Idempotency-Key": key },
        body: {
          expected_revision: cfg.expected_revision,
          reason: "Allocation deleted through React task editor; saved evidence retained.",
        },
      });
    },
    onSuccess: () => {
      setActionError(null);
      onSaved();
      onClose();
    },
    onError: (err) => {
      setActionError(
        err instanceof Error ? err.message : bilingual(lang, "删除失败，请重试。", "Delete failed."),
      );
    },
  });

  const cfg = configQuery.data;
  const groupCompleted: Record<string, number> = useMemo(() => {
    const out: Record<string, number> = {};
    for (const grp of cfg?.group_coverage?.groups || []) {
      out[grp.group_id] = (grp.members || []).reduce((acc, m) => acc + (Number(m.completed) || 0), 0);
    }
    return out;
  }, [cfg]);

  const basisOptions = [
    { value: "remaining", label: bilingual(lang, "按剩余量分配", "Distribute remaining work") },
    { value: "total", label: bilingual(lang, "按全量目标补齐", "Fill toward total targets") },
  ];
  const pairingOptions = [
    { value: "orthogonal", label: bilingual(lang, "正交交叉", "Orthogonal overlap") },
    { value: "paired", label: bilingual(lang, "配对交叉", "Paired overlap") },
  ];

  const previewErrorText =
    validationError ||
    (previewQuery.isError
      ? previewQuery.error instanceof Error
        ? previewQuery.error.message
        : bilingual(lang, "预览计算失败", "Preview failed")
      : null);

  return (
    <ModalDialog
      open={open}
      wide
      lang={lang}
      title={
        confirmDelete
          ? bilingual(lang, "删除整条任务分配", "Delete the whole allocation")
          : bilingual(lang, "修改任务分配", "Edit task allocation")
      }
      onClose={onClose}
      footer={
        confirmDelete ? (
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setConfirmDelete(false)}
            >
              {bilingual(lang, "返回编辑", "Back to editor")}
            </button>
            <button
              type="button"
              className="button button-danger ra-primary-touch"
              disabled={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
            >
              {deleteMutation.isPending
                ? bilingual(lang, "正在删除…", "Deleting…")
                : bilingual(lang, "确认删除分配", "Confirm delete")}
            </button>
          </>
        ) : (
          <div className="ra-alloc-footer">
            <div>
              {cfg?.editable && (
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => setConfirmDelete(true)}
                >
                  {bilingual(lang, "删除整条分配…", "Delete allocation…")}
                </button>
              )}
            </div>
            <div className="ra-alloc-footer-right">
              <button type="button" className="button button-quiet" onClick={onClose}>
                {bilingual(lang, "取消", "Cancel")}
              </button>
              <button
                type="button"
                className="button button-primary ra-primary-touch"
                disabled={
                  !cfg?.editable ||
                  Boolean(validationError) ||
                  !previewQuery.data?.preview_token ||
                  previewQuery.isFetching ||
                  applyMutation.isPending
                }
                onClick={() => applyMutation.mutate()}
              >
                {applyMutation.isPending
                  ? bilingual(lang, "正在保存…", "Saving…")
                  : bilingual(lang, "应用调整", "Apply changes")}
              </button>
            </div>
          </div>
        )
      }
    >
      <div className="ra-alloc-modal-root" data-react-island="allocation-editor">
        {configQuery.isLoading ? (
          <p className="muted">{bilingual(lang, "正在加载分配配置…", "Loading allocation…")}</p>
        ) : configQuery.isError ? (
          <div className="ra-inline-feedback is-error" role="alert">
            {configQuery.error instanceof Error
              ? configQuery.error.message
              : bilingual(lang, "加载分配配置失败", "Failed to load allocation")}
          </div>
        ) : !cfg ? null : confirmDelete ? (
          <div className="ra-alloc-delete-confirm">
            <p>
              <strong>{cfg.name || cfg.campaign_id}</strong>
            </p>
            <p className="muted">
              {bilingual(
                lang,
                `此任务将进入“已取消”，从当前分配中移除。已有 ${cfg.completed_slots} 份完成记录和 ${cfg.saved_pending_slots} 份保护待办全部保留，可在历史任务中查看。`,
                `This task will become Cancelled and leave current allocations. All ${cfg.completed_slots} completed and ${cfg.saved_pending_slots} protected pending slots are retained in history.`,
              )}
            </p>
          </div>
        ) : (
          <>
            <p className="muted ra-alloc-subtitle">
              {cfg.name || cfg.campaign_id} ·{" "}
              {bilingual(
                lang,
                `可调 ${cfg.movable_slots.toLocaleString()} 份 · 已完成与已保存记录自动保留`,
                `${cfg.movable_slots.toLocaleString()} movable slots · completed and saved work stays locked`,
              )}
            </p>

            <div className="ra-alloc-controls-bar">
              <div className="ra-unit-toggle" role="group" aria-label={bilingual(lang, "数值单位", "Input unit")}>
                <button
                  type="button"
                  className={`button ${unit === "percent" ? "button-primary" : "button-quiet"}`}
                  aria-pressed={unit === "percent"}
                  onClick={() => setUnit("percent")}
                >
                  %
                </button>
                <button
                  type="button"
                  className={`button ${unit === "count" ? "button-primary" : "button-quiet"}`}
                  aria-pressed={unit === "count"}
                  disabled={cfg.member_count <= 0}
                  onClick={() => setUnit("count")}
                >
                  {bilingual(lang, "条", "Count")}
                </button>
              </div>

              <div className="ra-alloc-select-wrap">
                <span className="muted">{bilingual(lang, "分配基数", "Basis")}</span>
                <UiSelect
                  value={quotaBasis}
                  options={basisOptions}
                  disabled={!cfg.editable}
                  ariaLabel={bilingual(lang, "分配基数", "Basis")}
                  onChange={(v) => setQuotaBasis(v === "total" ? "total" : "remaining")}
                />
              </div>

              {groups.length > 1 && (
                <div className="ra-alloc-select-wrap">
                  <span className="muted">{bilingual(lang, "交叉模式", "Pairing")}</span>
                  <UiSelect
                    value={pairingMode}
                    options={pairingOptions}
                    disabled={!cfg.editable}
                    ariaLabel={bilingual(lang, "交叉模式", "Pairing mode")}
                    onChange={(v) => setPairingMode(v === "paired" ? "paired" : "orthogonal")}
                  />
                </div>
              )}

              {cfg.editable && (
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => setGroups((prev) => [...prev, createNewAllocationGroup(prev)])}
                >
                  + {bilingual(lang, "添加分配组", "Add group")}
                </button>
              )}
            </div>

            <div className="ra-alloc-split-grid">
              <GroupShareEditor
                groups={groups}
                eligibleMembers={cfg.eligible_members || []}
                lang={lang}
                unit={unit}
                caseCount={cfg.member_count}
                quotaBasis={quotaBasis}
                groupCompleted={groupCompleted}
                editable={cfg.editable}
                onChange={(next, discrete) => {
                  setGroups(next);
                  if (discrete) {
                    const err = validateAllocationGroups(next, lang);
                    if (!err) {
                      const body = JSON.stringify({
                        groups: next.map((g) => ({
                          group_id: g.group_id,
                          coverage_percent: g.coverage_percent,
                          coverage_strategy: g.coverage_strategy || "overlap",
                          members: g.members
                            .filter((m) => m.name.trim())
                            .map((m) => ({ name: m.name, review_percent: m.review_percent })),
                        })),
                        cross_groups: [],
                        pairing_mode: pairingMode,
                        quota_basis: quotaBasis,
                        expected_revision: cfg.expected_revision,
                      });
                      schedulePreview(body, true);
                    }
                  }
                }}
                onBlurFlush={() => schedulePreview(serializedPayload, true)}
              />

              <AllocationPreviewPanel
                preview={previewQuery.data || (cfg.group_coverage ? { group_coverage: cfg.group_coverage, total_slots: cfg.movable_slots + cfg.completed_slots + cfg.saved_pending_slots } : null)}
                lang={lang}
                isUpdating={previewQuery.isFetching}
                errorText={previewErrorText}
                onRetry={() => void previewQuery.refetch()}
              />
            </div>

            {actionError && (
              <p className="ra-inline-feedback is-error" role="alert">
                {actionError}
              </p>
            )}
          </>
        )}
      </div>
    </ModalDialog>
  );
};
