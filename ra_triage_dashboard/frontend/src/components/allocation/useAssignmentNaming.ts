import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiRequest } from "../../api/client";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { AssignmentNameContext, ruleBasedAssignmentName } from "./allocationMath";

export interface UseAssignmentNamingOptions {
  enabled: boolean;
  isAdmin: boolean;
  context: AssignmentNameContext;
  lang: UiLanguage;
  resetKey?: string | number;
}

export interface AssignmentNamingState {
  name: string;
  setManualName: (value: string) => void;
  refreshName: () => void;
  resetName: () => void;
  source: "rule" | "llm" | "manual";
  status: "ready" | "loading";
  canRefresh: boolean;
  statusText: string;
  statusTitle: string;
  refreshLabel: string;
}

export function useAssignmentNaming({
  enabled,
  isAdmin,
  context,
  lang,
  resetKey,
}: UseAssignmentNamingOptions): AssignmentNamingState {
  const [name, setName] = useState("");
  const [manualEdited, setManualEdited] = useState(false);
  const [source, setSource] = useState<"rule" | "llm" | "manual">("rule");
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState<"ready" | "loading">("ready");

  const seqRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const appliedFingerprintRef = useRef("");

  const fallback = useMemo(() => ruleBasedAssignmentName(context), [context]);

  const payloadObj = useMemo(
    () => ({
      assignment_kind: context.assignmentKind,
      baseline_ids: context.baselineIds,
      case_count: context.caseCount,
      reviewers_per_issue: context.reviewersPerIssue,
      overlap_ratio: context.overlapRatio,
      member_count: context.memberCount,
      workflow_mode: context.workflowMode,
      model_run_id: context.modelRunId,
      comparison: context.comparison,
      draft_name: fallback,
    }),
    [context, fallback],
  );
  const fingerprint = useMemo(() => JSON.stringify(payloadObj), [payloadObj]);

  const available = Boolean(
    isAdmin &&
      context.baselineIds.length &&
      context.caseCount > 0 &&
      context.memberCount > 0 &&
      (context.assignmentKind !== "model_review" || context.modelRunId),
  );

  const requestSuggestion = useCallback(
    (immediate: boolean, force = false) => {
      if (timerRef.current) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      const seq = ++seqRef.current;
      if (!enabled) return;
      if (!force && manualEdited) return;
      if (!force && appliedFingerprintRef.current === fingerprint && source === "llm") return;
      if (!force) {
        setName(fallback);
        setSource("rule");
        if (appliedFingerprintRef.current !== fingerprint) setReason("");
      }
      if (!available) {
        setStatus("ready");
        return;
      }
      if (!force && appliedFingerprintRef.current === fingerprint) {
        setStatus("ready");
        return;
      }
      setStatus("loading");
      timerRef.current = window.setTimeout(async () => {
        try {
          const payload = await apiRequest<{
            suggestion?: string;
            source?: string;
            reason?: string;
          }>("/api/assignment-name-suggestion", {
            method: "POST",
            body: payloadObj,
          });
          if (seq !== seqRef.current) return;
          const suggestion = String(payload?.suggestion || "").trim();
          if (payload?.source === "llm" && suggestion) {
            setName(suggestion);
            setSource("llm");
            setReason("");
          } else {
            setName(fallback);
            setSource("rule");
            setReason(String(payload?.reason || ""));
          }
          appliedFingerprintRef.current = fingerprint;
        } catch {
          if (seq !== seqRef.current) return;
          setName(fallback);
          setSource("rule");
          setReason("request_failed");
          appliedFingerprintRef.current = fingerprint;
        } finally {
          if (seq === seqRef.current) setStatus("ready");
        }
      }, immediate ? 0 : 650);
    },
    [enabled, manualEdited, fingerprint, source, fallback, available, payloadObj],
  );

  useEffect(() => {
    if (!enabled) return;
    requestSuggestion(false, false);
    return () => {
      if (timerRef.current) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, fingerprint, available]); // eslint-disable-line react-hooks/exhaustive-deps

  const resetName = useCallback(() => {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    seqRef.current += 1;
    appliedFingerprintRef.current = "";
    setManualEdited(false);
    setSource("rule");
    setReason("");
    setStatus("ready");
    setName(fallback);
  }, [fallback]);

  useEffect(() => {
    if (resetKey !== undefined) {
      resetName();
    }
  }, [resetKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const setManualName = useCallback(
    (value: string) => {
      setName(value);
      const hasText = Boolean(value.trim());
      setManualEdited(hasText);
      if (hasText) {
        if (timerRef.current) {
          window.clearTimeout(timerRef.current);
          timerRef.current = null;
        }
        seqRef.current += 1;
        setSource("manual");
        setStatus("ready");
      } else {
        setSource("rule");
        appliedFingerprintRef.current = "";
      }
    },
    [],
  );

  const refreshName = useCallback(() => {
    if (!available || status === "loading") return;
    appliedFingerprintRef.current = "";
    setManualEdited(false);
    setSource("rule");
    setReason("");
    requestSuggestion(true, true);
  }, [available, status, requestSuggestion]);

  const effectiveSource: "rule" | "llm" | "manual" = manualEdited ? "manual" : source;
  const reasonMap: Record<string, string> = {
    not_configured: bilingual(lang, "未配置模型", "Model not configured"),
    timeout: bilingual(lang, "模型超时", "Model timed out"),
    unavailable: bilingual(lang, "模型暂不可用", "Model unavailable"),
    invalid_output: bilingual(lang, "名称未通过校验", "Name validation failed"),
    request_failed: bilingual(lang, "请求失败", "Request failed"),
  };
  const reasonText =
    effectiveSource === "rule" && status !== "loading" ? reasonMap[reason] || "" : "";

  const statusText =
    effectiveSource === "manual"
      ? bilingual(lang, "手动编辑", "Manual")
      : effectiveSource === "llm"
        ? bilingual(lang, "模型结果", "Model result")
        : status === "loading"
          ? bilingual(lang, "规则结果 · 优化中", "Rule · refining")
          : reasonText
            ? bilingual(lang, "规则结果 · 未更新", "Rule · unchanged")
            : bilingual(lang, "规则结果", "Rule result");

  const statusTitle =
    effectiveSource === "manual"
      ? bilingual(lang, "保留你手动输入的名称", "Your edited name is preserved")
      : effectiveSource === "llm"
        ? bilingual(lang, "当前名称来自模型", "The current name was generated by the model")
        : status === "loading"
          ? bilingual(
              lang,
              "当前为规则名称，正在请求模型优化",
              "Showing a rule name while requesting model refinement",
            )
          : reasonText
            ? `${reasonText} · ${bilingual(lang, "已使用规则名称，可点击刷新重试", "Using a rule name; refresh to retry")}`
            : bilingual(lang, "当前名称按实验配置规则生成", "The current name was generated from configuration rules");

  const refreshLabel =
    status === "loading"
      ? bilingual(lang, "正在生成实验名称", "Generating experiment name")
      : available
        ? bilingual(lang, "重新生成实验名称", "Regenerate experiment name")
        : bilingual(lang, "请先选择人员和分配范围", "Select people and an assignment scope first");

  return {
    name,
    setManualName,
    refreshName,
    resetName,
    source: effectiveSource,
    status,
    canRefresh: available && status !== "loading",
    statusText,
    statusTitle,
    refreshLabel,
  };
}
