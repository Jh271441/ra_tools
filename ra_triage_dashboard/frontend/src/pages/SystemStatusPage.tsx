import React, { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import type { components } from "../api/schema";
import { bilingual, formatCstTime, UiLanguage } from "../bridge/useWorkbenchBridge";
import { ChipTone, StatusChip } from "../components/ui/StatusChip";

export type SystemStatusPayload = components["schemas"]["SystemStatusResponse"] & {
  generated_at?: string;
  batch_prediction_enabled?: boolean;
  autotriage_push_enabled?: boolean;
  baseline?: Record<string, unknown>;
};

type BaselineItem = components["schemas"]["BaselineSummary"];

export function formatStatusDuration(seconds: number | null | undefined, lang: UiLanguage): string {
  const value = Math.max(0, Number(seconds) || 0);
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  if (days) return lang === "en" ? `${days}d ${hours}h` : `${days} 天 ${hours} 小时`;
  if (hours) return lang === "en" ? `${hours}h ${minutes}m` : `${hours} 小时 ${minutes} 分`;
  return lang === "en" ? `${minutes}m` : `${minutes} 分钟`;
}

export function formatStatusBytes(bytes: number | null | undefined): string {
  const value = Math.max(0, Number(bytes) || 0);
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let index = 0;
  let size = value;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  const digits = index >= 1 ? 1 : 0;
  return `${size.toFixed(digits)} ${units[index]}`;
}

function baselineLifecycleLabel(status: string | null | undefined, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    checking: ["统计中", "Counting"],
    unavailable: ["统计异常", "Count unavailable"],
    registered: ["已注册", "Registered"],
    collecting: ["采集中", "Collecting"],
    partial: ["部分可用", "Partial"],
    verifying: ["校验中", "Verifying"],
    complete: ["完整", "Complete"],
    blocked: ["阻塞", "Blocked"],
    ready: ["就绪", "Ready"],
  };
  const pair = map[String(status || "")];
  return pair ? bilingual(lang, pair[0], pair[1]) : String(status || "—");
}

function problemLabel(key: string, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    database_unavailable: ["数据库不可用", "Database unavailable"],
    database_not_persistent: ["数据库未持久化", "Database not persistent"],
    baseline_unavailable: ["基线数据不可用", "Baseline data unavailable"],
    backup_missing: ["缺少数据库备份", "Database backup missing"],
    backup_checksum_missing: ["缺少备份校验文件", "Backup checksum missing"],
    backup_stale: ["数据库备份已过期", "Database backup stale"],
    backup_schedule_unregistered: ["自动备份计划未注册", "Backup schedule unregistered"],
    disk_space_low: ["磁盘可用空间不足", "Low disk space"],
  };
  const pair = map[key];
  return pair ? bilingual(lang, pair[0], pair[1]) : key;
}

function formatCount(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value.toLocaleString()
    : "—";
}

interface StatusCardProps {
  title: string;
  chip: string;
  tone?: ChipTone;
  rows: Array<[string, string]>;
  wide?: boolean;
  children?: React.ReactNode;
}

const StatusCard: React.FC<StatusCardProps> = ({
  title,
  chip,
  tone = "ok",
  rows,
  wide = false,
  children,
}) => (
  <article className={`system-status-card${wide ? " system-status-card--wide" : ""}`}>
    <div className="system-status-card-head">
      <h3>{title}</h3>
      <StatusChip label={chip} tone={tone} />
    </div>
    {rows.length > 0 && (
      <div className="system-status-rows">
        {rows.map(([label, value]) => (
          <div className="system-status-row" key={label}>
            <span>{label}</span>
            <strong title={value}>{value}</strong>
          </div>
        ))}
      </div>
    )}
    {children}
  </article>
);

export interface SystemStatusPageProps {
  active: boolean;
  lang: UiLanguage;
}

export const SystemStatusPage: React.FC<SystemStatusPageProps> = ({ active, lang }) => {
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  const statusQuery = useQuery<SystemStatusPayload>({
    queryKey: ["system-status"],
    queryFn: ({ signal }) => apiRequest<SystemStatusPayload>("/api/status", { signal }),
    enabled: active,
    staleTime: 10_000,
    refetchInterval: (query) => {
      if (!active) return false;
      const baselines = query.state.data?.baselines || [];
      const busy = baselines.some((b) =>
        ["pending", "refreshing"].includes(String(b.media_ready?.coverage_status || "")),
      );
      return busy ? 2000 : false;
    },
  });

  useEffect(() => {
    const data = statusQuery.data;
    if (!data || typeof window === "undefined") return;
    const win = window as unknown as {
      __RA_TRIAGE_STATE__?: { systemStatus?: unknown; config?: Record<string, unknown> };
      state?: { systemStatus?: unknown; config?: Record<string, unknown> };
      renderConfig?: () => void;
    };
    const legacyState = win.__RA_TRIAGE_STATE__ || win.state;
    if (legacyState) {
      legacyState.systemStatus = data;
      if (data.baseline || data.trail_sync) {
        legacyState.config = {
          ...(legacyState.config || {}),
          baseline: data.baseline || legacyState.config?.baseline,
          trail_sync: data.trail_sync || legacyState.config?.trail_sync,
        };
        win.renderConfig?.();
      }
    }
  }, [statusQuery.data]);

  const handleForceRefresh = async () => {
    setRefreshing(true);
    const win =
      typeof window !== "undefined"
        ? (window as unknown as { showToast?: (msg: string, isError?: boolean) => void })
        : null;
    try {
      const fresh = await apiRequest<SystemStatusPayload>("/api/status?refresh=true");
      queryClient.setQueryData(["system-status"], fresh);
      win?.showToast?.(bilingual(lang, "系统状态已刷新。", "System status refreshed."));
    } catch (err) {
      win?.showToast?.(
        err instanceof Error ? err.message : bilingual(lang, "刷新系统状态失败。", "Failed to refresh status."),
        true,
      );
    } finally {
      setRefreshing(false);
    }
  };

  const data = statusQuery.data;
  const database = data?.database;
  const backups = data?.backups as
    | (components["schemas"]["BackupStatus"] & { schedule?: string })
    | undefined;
  const volume = data?.volume as
    | (components["schemas"]["VolumeStatus"] & { available?: boolean })
    | undefined;
  const baselines: BaselineItem[] =
    Array.isArray(data?.baselines) && data.baselines.length > 0
      ? data.baselines
      : data?.baseline
        ? [data.baseline as BaselineItem]
        : [];
  const trail = (data?.trail_sync || {}) as { status?: string; message?: string };
  const gateway = (data?.model_gateway || {}) as { configured?: boolean };
  const application = data?.application;
  const legacyCutover = (data?.legacy_cutover || {}) as {
    policies?: Array<{ baseline_scope?: string; policy?: string }>;
  };
  const overall = data?.overall || { status: "degraded", problems: [] };
  const healthy = overall.status === "healthy";
  const problems = (overall.problems || []).map((k) => problemLabel(k, lang));

  const backupReady = Boolean(
    backups?.available && backups?.latest_checksum_present && backups?.schedule_registered,
  );
  const databaseReady = Boolean(
    database?.ok && (database?.backend !== "postgresql" || database?.persistent_data),
  );
  const baselineReady =
    baselines.length > 0 &&
    baselines.every(
      (item) =>
        ["registered", "ready"].includes(String(item.registration_status || item.status || "")) &&
        Number(item.count || 0) > 0,
    );
  const baselineMediaReady =
    baselines.length > 0 &&
    baselines.every((item) =>
      ["complete", "ready"].includes(String(item.media_status || item.status || "")),
    );
  const mediaBusy = baselines.some((item) =>
    ["pending", "refreshing"].includes(String(item.media_ready?.coverage_status || "")),
  );
  const mediaError = baselines.some((item) => item.media_ready?.coverage_status === "error");
  const assetsReady = Boolean(
    data?.ra_auto_triage_root_available &&
      data?.ares_manifest_available &&
      data?.camera_cache_root_available,
  );
  const gatewayReady = Boolean(gateway.configured);
  const usedPercent = Math.max(0, Math.min(100, Number(volume?.used_percent) || 0));
  const conflictCount = Array.isArray(data?.baseline_conflicts) ? data.baseline_conflicts.length : 0;
  const volumeOk = Boolean(volume?.available && Number(volume?.free_bytes || 0) >= 1024 ** 3);

  const scopeLabels = new Map(baselines.map((b) => [b.scope, b.label || b.id]));
  const legacyPolicies = Array.isArray(legacyCutover.policies) ? legacyCutover.policies : [];
  const legacyModeLabels: Record<string, [string, string]> = {
    legacy: ["沿用现有记录", "Existing records"],
    shadow: ["迁移核对中", "Migration checks"],
    canonical: ["新版记录", "New records"],
  };

  return (
    <div className="ra-system-status-root" data-react-island="system-status">
      <div className="compact-page-lead system-status-lead">
        <div className="system-status-actions">
          <span id="systemStatusUpdatedAt">
            {data
              ? `${bilingual(lang, "更新于", "Updated")} ${formatCstTime(data.generated_at, lang)}`
              : "—"}
          </span>
          <button
            className="button button-quiet"
            id="refreshSystemStatusButton"
            type="button"
            disabled={refreshing || statusQuery.isFetching}
            onClick={() => void handleForceRefresh()}
          >
            {refreshing || statusQuery.isFetching
              ? bilingual(lang, "刷新中…", "Refreshing…")
              : bilingual(lang, "刷新状态", "Refresh status")}
          </button>
        </div>
      </div>

      <section
        className={`system-status-hero${statusQuery.isError || (data && !healthy) ? " degraded" : ""}`}
        id="systemStatusHero"
        aria-live="polite"
      >
        {statusQuery.isLoading ? (
          <div className="system-status-loading">
            {bilingual(lang, "正在读取系统状态…", "Loading system status…")}
          </div>
        ) : statusQuery.isError ? (
          <div className="system-status-summary">
            <div className="system-status-indicator" aria-hidden="true">
              !
            </div>
            <div>
              <h2>{bilingual(lang, "无法读取系统状态", "Unable to load system status")}</h2>
              <p>
                {statusQuery.error instanceof Error
                  ? statusQuery.error.message
                  : bilingual(lang, "请稍后点击刷新重试。", "Please refresh to retry.")}
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="system-status-summary">
              <div className="system-status-indicator" aria-hidden="true">
                {healthy ? "✓" : "!"}
              </div>
              <div>
                <h2>
                  {healthy
                    ? bilingual(lang, "关键系统运行正常", "Core systems healthy")
                    : bilingual(lang, "系统存在待关注异常", "System attention required")}
                </h2>
                <p>
                  {healthy
                    ? bilingual(
                        lang,
                        "服务、持久化数据库与备份保护均已就绪。",
                        "Application, persistent database, and backup protection are ready.",
                      )
                    : problems.join(" · ") ||
                      bilingual(lang, "请检查下方详细状态卡片。", "Review the status cards below.")}
                </p>
              </div>
            </div>
            <div className="system-status-build">
              <span>{bilingual(lang, "部署版本", "Build commit")}</span>
              <code>{application?.build_commit || data?.build_commit || "unverified"}</code>
            </div>
          </>
        )}
      </section>

      {data && (
        <div className="system-status-grid" id="systemStatusGrid">
          <StatusCard
            title={bilingual(lang, "应用服务", "Application")}
            chip={bilingual(lang, "在线", "Online")}
            rows={[
              [
                bilingual(lang, "运行时间", "Uptime"),
                formatStatusDuration(application?.uptime_seconds, lang),
              ],
              [bilingual(lang, "启动时间", "Started"), formatCstTime(application?.started_at, lang)],
              [bilingual(lang, "共享数据版本", "Shared revision"), String(database?.revision ?? "—")],
            ]}
          />

          <StatusCard
            title={bilingual(lang, "数据库", "Database")}
            chip={databaseReady ? bilingual(lang, "正常", "Healthy") : bilingual(lang, "异常", "Issue")}
            tone={databaseReady ? "ok" : "fail"}
            rows={[
              [
                bilingual(lang, "存储引擎", "Backend"),
                database?.backend === "postgresql" ? "PostgreSQL" : "SQLite",
              ],
              [
                bilingual(lang, "持久化", "Persistence"),
                database?.persistent_data
                  ? bilingual(lang, "/volume 持久卷", "/volume persistent")
                  : bilingual(lang, "本地存储", "Local storage"),
              ],
              [
                bilingual(lang, "连接延迟", "Latency"),
                database?.latency_ms == null ? "—" : `${database.latency_ms} ms`,
              ],
              [
                bilingual(lang, "版本 / Migration", "Version / Migrations"),
                `${database?.server_version || "—"} · ${database?.migration_count ?? 0}`,
              ],
              [bilingual(lang, "连接池上限", "Pool limit"), String(database?.pool_max_size || "—")],
            ]}
          />

          <StatusCard
            title={bilingual(lang, "数据库备份", "Database backups")}
            chip={
              backupReady
                ? bilingual(lang, "已保护", "Protected")
                : bilingual(lang, "需关注", "Attention")
            }
            tone={backupReady ? "ok" : "warn"}
            rows={[
              [
                bilingual(lang, "最近备份", "Latest backup"),
                backups?.latest_created_at ? formatCstTime(backups.latest_created_at, lang) : "—",
              ],
              [
                bilingual(lang, "备份距今", "Backup age"),
                backups?.latest_age_seconds == null
                  ? "—"
                  : formatStatusDuration(backups.latest_age_seconds, lang),
              ],
              [
                bilingual(lang, "大小 / 份数", "Size / Copies"),
                `${formatStatusBytes(backups?.latest_size_bytes)} · ${backups?.count || 0}`,
              ],
              [
                bilingual(lang, "SHA-256 文件", "SHA-256 checksum"),
                backups?.latest_checksum_present
                  ? bilingual(lang, "已生成", "Present")
                  : bilingual(lang, "缺失", "Missing"),
              ],
              [
                bilingual(lang, "自动计划", "Schedule"),
                backups?.schedule_registered
                  ? `${backups.schedule || backups.schedule_line || "—"} · ${bilingual(lang, "服务器时间", "Server time")}`
                  : bilingual(lang, "未注册", "Not registered"),
              ],
            ]}
          />

          <StatusCard
            title={bilingual(lang, "数据与媒体", "Data & media")}
            chip={
              mediaError
                ? bilingual(lang, "统计异常", "Count unavailable")
                : mediaBusy
                  ? bilingual(lang, "统计更新中", "Updating counts")
                  : baselineReady && baselineMediaReady && assetsReady
                    ? bilingual(lang, "就绪", "Ready")
                    : bilingual(lang, "部分可用", "Partial")
            }
            tone={
              mediaError
                ? "warn"
                : mediaBusy
                  ? "neutral"
                  : baselineReady && baselineMediaReady && assetsReady
                    ? "ok"
                    : "warn"
            }
            wide
            rows={[
              [bilingual(lang, "Issue 冲突", "Issue conflicts"), String(conflictCount)],
              [
                bilingual(lang, "Camera 缓存", "Camera cache"),
                data.camera_cache_root_available
                  ? bilingual(lang, "可用", "Available")
                  : bilingual(lang, "不可用", "Unavailable"),
              ],
              [
                bilingual(lang, "BEV 视频", "BEV video"),
                data.ares_video_root_available
                  ? bilingual(lang, "可用", "Available")
                  : bilingual(lang, "不可用", "Unavailable"),
              ],
            ]}
          >
            <div
              className="system-media-table-wrap"
              tabIndex={0}
              role="region"
              aria-label={bilingual(lang, "数据与媒体", "Data & media")}
            >
              <table className="system-media-table">
                <thead>
                  <tr>
                    <th scope="col">{bilingual(lang, "数据集", "Dataset")}</th>
                    <th scope="col">{bilingual(lang, "成员", "Members")}</th>
                    <th scope="col">BEV</th>
                    <th scope="col">{bilingual(lang, "BEV 视频", "BEV video")}</th>
                    <th scope="col">Camera</th>
                    <th scope="col">{bilingual(lang, "媒体状态", "Media status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {baselines.length === 0 ? (
                    <tr>
                      <td colSpan={6}>
                        {bilingual(lang, "暂无数据集状态", "No dataset status available")}
                      </td>
                    </tr>
                  ) : (
                    baselines.map((item) => {
                      const membership = item.membership;
                      const media = item.media_ready;
                      const expected = membership?.expected_count ?? item.count;
                      const status = item.media_status || item.status;
                      const registered = ["registered", "ready"].includes(
                        String(item.registration_status || item.status || ""),
                      );
                      const ready = registered && ["complete", "ready"].includes(String(status || ""));
                      const missingEntries = Object.entries(item.missing_media || {})
                        .filter(([, count]) => Number(count) > 0)
                        .map(([key, count]) => {
                          const label =
                            key === "bev"
                              ? "BEV"
                              : key === "video"
                                ? bilingual(lang, "视频", "Video")
                                : key === "camera"
                                  ? "Camera"
                                  : key;
                          return `${label} ${bilingual(lang, "缺少", "missing")} ${formatCount(count)}`;
                        });
                      if ((media?.failure_count || 0) > 0) {
                        missingEntries.push(
                          bilingual(
                            lang,
                            `采集错误 ${formatCount(media?.failure_count)} 项`,
                            `${formatCount(media?.failure_count)} capture errors`,
                          ),
                        );
                      }
                      return (
                        <tr key={item.id || item.scope}>
                          <th scope="row">{item.label || item.id || "—"}</th>
                          <td>{`${formatCount(membership?.registered_count ?? item.count)} / ${formatCount(expected)}`}</td>
                          <td>{`${formatCount(media?.bev_indexed_issues)} / ${formatCount(expected)}`}</td>
                          <td>{`${formatCount(media?.video_indexed_issues)} / ${formatCount(expected)}`}</td>
                          <td>{`${formatCount(media?.camera_indexed_issues)} / ${formatCount(expected)}`}</td>
                          <td>
                            <StatusChip
                              label={
                                registered
                                  ? baselineLifecycleLabel(status, lang)
                                  : bilingual(lang, "成员异常", "Membership issue")
                              }
                              tone={ready ? "ok" : status === "blocked" ? "fail" : "warn"}
                            />
                            {missingEntries.length > 0 && (
                              <small className="system-media-missing">
                                {missingEntries.join(" · ")}
                              </small>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
            <p className="system-status-note">
              {mediaError
                ? bilingual(
                    lang,
                    "媒体统计暂不可用，请稍后刷新；已有计数保留上次结果。",
                    "Media counts are unavailable; refresh later. Existing counts retain the last result.",
                  )
                : mediaBusy
                  ? bilingual(
                      lang,
                      "媒体统计正在后台更新，完成后本页自动刷新；已有计数为上次结果。",
                      "Media counts are updating in the background. This page refreshes when ready; existing counts show the last result.",
                    )
                  : bilingual(
                      lang,
                      "按各数据集成员统计，BEV、视频与 Camera 分别计数。",
                      "Counts are scoped to each dataset's members; BEV, video and Camera are counted independently.",
                    )}
            </p>
          </StatusCard>

          <StatusCard
            title={bilingual(lang, "模型与外部集成", "Models & integrations")}
            chip={
              gatewayReady
                ? bilingual(lang, "网关已配置", "Gateway configured")
                : bilingual(lang, "网关未配置", "Gateway missing")
            }
            tone={gatewayReady ? "ok" : "warn"}
            rows={[
              [
                bilingual(lang, "运行模式", "Deployment mode"),
                application?.deployment_mode === "production"
                  ? bilingual(lang, "生产模式", "Production")
                  : bilingual(lang, "开发模式", "Development"),
              ],
              [
                bilingual(lang, "模型网关", "Model gateway"),
                gateway.configured
                  ? bilingual(lang, "服务端凭据已就绪", "Server credentials ready")
                  : bilingual(lang, "未配置", "Not configured"),
              ],
              [
                bilingual(lang, "批次预测", "Batch prediction"),
                data.batch_prediction_enabled
                  ? bilingual(lang, "已启用", "Enabled")
                  : bilingual(lang, "未启用", "Disabled"),
              ],
              [
                bilingual(lang, "看板手动推送", "Dashboard publication"),
                data.autotriage_push_enabled
                  ? bilingual(lang, "已启用", "Enabled")
                  : bilingual(lang, "未启用", "Disabled"),
              ],
              [
                bilingual(lang, "Trail 模型字段", "Trail model fields"),
                ["ready", "preview_ready"].includes(String(trail.status || ""))
                  ? bilingual(lang, "可用", "Available")
                  : bilingual(lang, "暂不可用", "Unavailable"),
              ],
            ]}
          >
            <p className="system-status-note">
              {bilingual(
                lang,
                "手动推送开关仅作用于本看板；每日推理与回刷进度请查看“每日任务”。",
                "The publication switch applies to this dashboard. Check Daily tasks for scheduled inference and publication.",
              )}
            </p>
            {trail.message && (
              <details className="system-status-diagnostics">
                <summary>{bilingual(lang, "连接详情", "Connection details")}</summary>
                <p className="system-status-note">{trail.message}</p>
              </details>
            )}
          </StatusCard>

          <StatusCard
            title={bilingual(lang, "历史复核数据", "Historical reviews")}
            chip={
              legacyPolicies.length
                ? bilingual(lang, "读取方式", "Read mode")
                : bilingual(lang, "沿用现有记录", "Existing records")
            }
            tone="neutral"
            rows={legacyPolicies.map((item) => {
              const pair = legacyModeLabels[String(item.policy || "")];
              return [
                scopeLabels.get(String(item.baseline_scope || "")) ||
                  bilingual(lang, "数据集", "Dataset"),
                pair ? bilingual(lang, pair[0], pair[1]) : bilingual(lang, "待确认", "Unknown"),
              ];
            })}
          >
            <p className="system-status-note">
              {bilingual(
                lang,
                "这里说明历史复核记录的读取方式。当前问题标注与判错复核仍按用户权限提交。",
                "This describes how historical reviews are read. Current labeling and reviews follow user permissions.",
              )}
            </p>
          </StatusCard>

          <StatusCard
            title={bilingual(lang, "数据卷容量", "Volume capacity")}
            chip={
              volumeOk
                ? bilingual(lang, "容量正常", "Capacity OK")
                : bilingual(lang, "空间偏低", "Low space")
            }
            tone={volumeOk ? "ok" : "fail"}
            rows={[
              [
                bilingual(lang, "已使用", "Used"),
                `${formatStatusBytes(volume?.used_bytes)} · ${usedPercent}%`,
              ],
              [bilingual(lang, "可用空间", "Free"), formatStatusBytes(volume?.free_bytes)],
              [bilingual(lang, "总容量", "Total"), formatStatusBytes(volume?.total_bytes)],
            ]}
          >
            <div className="system-capacity">
              <div className="system-capacity-track">
                <span
                  className={usedPercent >= 95 ? "warn" : ""}
                  style={{ width: `${usedPercent}%` }}
                />
              </div>
            </div>
          </StatusCard>
        </div>
      )}
    </div>
  );
};
