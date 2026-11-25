import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, formatCstTime, UiLanguage } from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { CASE_PAGE_SIZES, DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { StatusChip } from "../components/ui/StatusChip";
import { UiSelect } from "../components/ui/UiSelect";

export interface AccessUser {
  username: string;
  role: string;
  intent_permission?: string;
  annotation_role?: string;
  updated_at?: string;
  updated_by?: string;
}

export interface MentionUser {
  username: string;
  display_name?: string;
  enabled?: boolean;
  updated_at?: string;
}

interface AccessDraft {
  role: string;
  intent_permission: string;
  annotation_role: string;
}

export interface UsersPageProps {
  active: boolean;
  lang: UiLanguage;
  isAdmin: boolean;
  sessionLoading?: boolean;
}

function readInitialPagination(): { page: number; pageSize: number } {
  if (typeof window === "undefined") return { page: 1, pageSize: DEFAULT_CASE_PAGE_SIZE };
  const params = new URLSearchParams(window.location.search);
  const rawSize = Number(params.get("page_size"));
  const pageSize = CASE_PAGE_SIZES.includes(rawSize as (typeof CASE_PAGE_SIZES)[number])
    ? rawSize
    : DEFAULT_CASE_PAGE_SIZE;
  const page = Math.max(1, Number(params.get("page")) || 1);
  return { page, pageSize };
}

function syncUrlPagination(page: number, pageSize: number) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("page", String(page));
  url.searchParams.set("page_size", String(pageSize));
  window.history.replaceState(window.history.state, "", url.toString());
}

function notifyLegacyRevision(result: unknown) {
  if (typeof window === "undefined") return;
  const win = window as unknown as { acknowledgeLocalChange?: (payload: unknown) => void };
  if (typeof win.acknowledgeLocalChange === "function") {
    win.acknowledgeLocalChange(result);
  }
}

function emitToast(message: string, isError = false) {
  if (typeof window === "undefined") return;
  const win = window as unknown as { showToast?: (msg: string, err?: boolean) => void };
  win.showToast?.(message, isError);
}

function refreshLegacySession() {
  if (typeof window === "undefined") return;
  const win = window as unknown as { loadSession?: () => Promise<void> | void };
  void win.loadSession?.();
}

export const UsersPage: React.FC<UsersPageProps> = ({
  active,
  lang,
  isAdmin,
  sessionLoading = false,
}) => {
  const queryClient = useQueryClient();
  const initial = useMemo(() => readInitialPagination(), []);
  const [page, setPage] = useState(initial.page);
  const [pageSize, setPageSize] = useState(initial.pageSize);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");

  const [newUsername, setNewUsername] = useState("");
  const [newRole, setNewRole] = useState("writer");
  const [newIntentPerm, setNewIntentPerm] = useState("manage");
  const [newAnnotationRole, setNewAnnotationRole] = useState("");

  const [accessDrafts, setAccessDrafts] = useState<Record<string, AccessDraft>>({});
  const [savingUser, setSavingUser] = useState<string | null>(null);
  const [deletingUser, setDeletingUser] = useState<string | null>(null);
  const [confirmRemoveUser, setConfirmRemoveUser] = useState<string | null>(null);

  const [newMentionUsername, setNewMentionUsername] = useState("");
  const [mentionSearch, setMentionSearch] = useState("");
  const [mentionPage, setMentionPage] = useState(1);
  const [mentionPageSize, setMentionPageSize] = useState<number>(DEFAULT_CASE_PAGE_SIZE);
  const [mentionDrafts, setMentionDrafts] = useState<Record<string, boolean>>({});
  const [savingMention, setSavingMention] = useState<string | null>(null);
  const [deletingMention, setDeletingMention] = useState<string | null>(null);
  const [confirmRemoveMention, setConfirmRemoveMention] = useState<string | null>(null);

  const [feedback, setFeedback] = useState<{ text: string; isError: boolean } | null>(null);
  const [mentionFeedback, setMentionFeedback] = useState<{ text: string; isError: boolean } | null>(
    null,
  );

  const accessQuery = useQuery<{ items: AccessUser[] }>({
    queryKey: ["access-users"],
    queryFn: ({ signal }) => apiRequest<{ items: AccessUser[] }>("/api/access-users", { signal }),
    enabled: active && isAdmin,
    staleTime: 15_000,
  });

  const mentionQuery = useQuery<{ items: MentionUser[] }>({
    queryKey: ["mention-users"],
    queryFn: ({ signal }) => apiRequest<{ items: MentionUser[] }>("/api/mention-users", { signal }),
    enabled: active && isAdmin,
    staleTime: 15_000,
  });

  useEffect(() => {
    if (!accessQuery.data?.items || typeof window === "undefined") return;
    const win = window as unknown as {
      __RA_TRIAGE_STATE__?: { accessUsers?: AccessUser[] };
      state?: { accessUsers?: AccessUser[] };
    };
    const legacyState = win.__RA_TRIAGE_STATE__ || win.state;
    if (legacyState) legacyState.accessUsers = accessQuery.data.items;
  }, [accessQuery.data]);

  useEffect(() => {
    if (!mentionQuery.data?.items || typeof window === "undefined") return;
    const win = window as unknown as {
      __RA_TRIAGE_STATE__?: { mentionUsers?: MentionUser[] };
      state?: { mentionUsers?: MentionUser[] };
    };
    const legacyState = win.__RA_TRIAGE_STATE__ || win.state;
    if (legacyState) legacyState.mentionUsers = mentionQuery.data.items;
  }, [mentionQuery.data]);

  const saveUserMutation = useMutation({
    mutationFn: (payload: {
      username: string;
      role: string;
      intent_permission: string;
      annotation_role: string;
      clearForm?: boolean;
    }) => {
      setSavingUser(payload.clearForm ? "__create__" : payload.username);
      return apiRequest(`/api/access-users/${encodeURIComponent(payload.username)}`, {
        method: "PUT",
        body: {
          role: payload.role,
          intent_permission: payload.intent_permission,
          ...(payload.annotation_role ? { annotation_role: payload.annotation_role } : {}),
        },
      });
    },
    onSuccess: (result, variables) => {
      notifyLegacyRevision(result);
      if (variables.clearForm) setNewUsername("");
      setAccessDrafts((prev) => {
        const next = { ...prev };
        delete next[variables.username];
        return next;
      });
      const msg = bilingual(lang, "用户权限已保存。", "User permissions saved.");
      setFeedback({ text: msg, isError: false });
      emitToast(msg, false);
      void queryClient.invalidateQueries({ queryKey: ["access-users"] });
      void queryClient.invalidateQueries({ queryKey: ["mention-users"] });
      void queryClient.invalidateQueries({ queryKey: ["session"] });
      refreshLegacySession();
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : bilingual(lang, "保存失败", "Save failed");
      setFeedback({ text: msg, isError: true });
      emitToast(msg, true);
    },
    onSettled: () => setSavingUser(null),
  });

  const deleteUserMutation = useMutation({
    mutationFn: (username: string) => {
      setDeletingUser(username);
      return apiRequest(`/api/access-users/${encodeURIComponent(username)}`, { method: "DELETE" });
    },
    onSuccess: (result, username) => {
      notifyLegacyRevision(result);
      setConfirmRemoveUser(null);
      setAccessDrafts((prev) => {
        const next = { ...prev };
        delete next[username];
        return next;
      });
      const msg = bilingual(lang, "用户权限已移除。", "User removed.");
      setFeedback({ text: msg, isError: false });
      emitToast(msg, false);
      void queryClient.invalidateQueries({ queryKey: ["access-users"] });
      void queryClient.invalidateQueries({ queryKey: ["session"] });
      refreshLegacySession();
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : bilingual(lang, "删除失败", "Remove failed");
      setFeedback({ text: msg, isError: true });
      emitToast(msg, true);
    },
    onSettled: () => setDeletingUser(null),
  });

  const saveMentionMutation = useMutation({
    mutationFn: (payload: { username: string; enabled: boolean; clearForm?: boolean }) => {
      setSavingMention(payload.clearForm ? "__create__" : payload.username);
      return apiRequest(`/api/mention-users/${encodeURIComponent(payload.username)}`, {
        method: "PUT",
        body: { enabled: payload.enabled },
      });
    },
    onSuccess: (result, variables) => {
      notifyLegacyRevision(result);
      if (variables.clearForm) setNewMentionUsername("");
      setMentionDrafts((prev) => {
        const next = { ...prev };
        delete next[variables.username];
        return next;
      });
      const msg = bilingual(lang, "可 @ 人员状态已保存。", "Mention directory entry saved.");
      setMentionFeedback({ text: msg, isError: false });
      emitToast(msg, false);
      void queryClient.invalidateQueries({ queryKey: ["mention-users"] });
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : bilingual(lang, "保存失败", "Save failed");
      setMentionFeedback({ text: msg, isError: true });
      emitToast(msg, true);
    },
    onSettled: () => setSavingMention(null),
  });

  const deleteMentionMutation = useMutation({
    mutationFn: (username: string) => {
      setDeletingMention(username);
      return apiRequest(`/api/mention-users/${encodeURIComponent(username)}`, { method: "DELETE" });
    },
    onSuccess: (result, username) => {
      notifyLegacyRevision(result);
      setConfirmRemoveMention(null);
      setMentionDrafts((prev) => {
        const next = { ...prev };
        delete next[username];
        return next;
      });
      const msg = bilingual(lang, "可 @ 人员已移除。", "Mention user removed.");
      setMentionFeedback({ text: msg, isError: false });
      emitToast(msg, false);
      void queryClient.invalidateQueries({ queryKey: ["mention-users"] });
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : bilingual(lang, "删除失败", "Remove failed");
      setMentionFeedback({ text: msg, isError: true });
      emitToast(msg, true);
    },
    onSettled: () => setDeletingMention(null),
  });

  const allUsers = accessQuery.data?.items || [];
  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return allUsers.filter((u) => {
      if (roleFilter !== "all" && u.role !== roleFilter) return false;
      if (q && !u.username.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [allUsers, roleFilter, search]);

  const totalPages = Math.max(1, Math.ceil(filteredUsers.length / pageSize));
  const clampedPage = Math.max(1, Math.min(totalPages, page));
  const visibleUsers = filteredUsers.slice((clampedPage - 1) * pageSize, clampedPage * pageSize);

  useEffect(() => {
    if (!active || !accessQuery.data) return;
    if (clampedPage !== page) {
      setPage(clampedPage);
      syncUrlPagination(clampedPage, pageSize);
    }
  }, [active, accessQuery.data, clampedPage, page, pageSize]);

  const allMentions = mentionQuery.data?.items || [];
  const filteredMentions = useMemo(() => {
    const q = mentionSearch.trim().toLowerCase();
    if (!q) return allMentions;
    return allMentions.filter(
      (m) =>
        m.username.toLowerCase().includes(q) ||
        String(m.display_name || "")
          .toLowerCase()
          .includes(q),
    );
  }, [allMentions, mentionSearch]);

  const mentionTotalPages = Math.max(1, Math.ceil(filteredMentions.length / mentionPageSize));
  const clampedMentionPage = Math.max(1, Math.min(mentionTotalPages, mentionPage));
  const visibleMentions = filteredMentions.slice(
    (clampedMentionPage - 1) * mentionPageSize,
    clampedMentionPage * mentionPageSize,
  );

  const roleOptions = [
    { value: "writer", label: bilingual(lang, "可写", "Writer") },
    { value: "admin", label: bilingual(lang, "管理员", "Admin") },
  ];
  const roleFilterOptions = [
    { value: "all", label: bilingual(lang, "全部角色", "All roles") },
    ...roleOptions,
  ];
  const intentOptions = [
    { value: "manage", label: bilingual(lang, "创建与分配", "Manage") },
    { value: "annotate", label: bilingual(lang, "仅标注", "Annotate") },
    { value: "view", label: bilingual(lang, "仅查看", "View only") },
  ];
  const annotationRoleOptions = [
    { value: "", label: bilingual(lang, "按目录默认身份", "Directory default") },
    { value: "rd", label: "RD" },
    { value: "te", label: "TE" },
  ];
  const rowAnnotationRoleOptions = [
    { value: "rd", label: "RD" },
    { value: "te", label: "TE" },
  ];

  const handlePageChange = (nextPage: number) => {
    setPage(nextPage);
    syncUrlPagination(nextPage, pageSize);
  };

  const handlePageSizeChange = (nextSize: number) => {
    setPageSize(nextSize);
    setPage(1);
    syncUrlPagination(1, nextSize);
  };

  const getDraft = (user: AccessUser): AccessDraft =>
    accessDrafts[user.username] || {
      role: user.role || "writer",
      intent_permission: user.intent_permission || "manage",
      annotation_role: user.annotation_role || "rd",
    };

  const updateDraft = (user: AccessUser, patch: Partial<AccessDraft>) => {
    setAccessDrafts((prev) => ({
      ...prev,
      [user.username]: { ...getDraft(user), ...patch },
    }));
  };

  if (sessionLoading) {
    return (
      <div className="ra-users-root" data-react-island="users">
        <section className="access-panel">
          <p className="no-asset">
            {bilingual(lang, "正在验证管理员权限…", "Verifying administrator access…")}
          </p>
        </section>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="ra-users-root" data-react-island="users">
        <section className="access-panel">
          <p className="no-asset">
            {bilingual(
              lang,
              "该页面仅限 Dashboard 管理员访问。",
              "This page is restricted to Dashboard administrators.",
            )}
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="ra-users-root" data-react-island="users">
      <section className="access-panel">
        <div className="access-heading">
          <div>
            <span className="eyebrow">ACCESS CONTROL</span>
            <h2>{bilingual(lang, "使用者权限", "User access")}</h2>
            <p>
              {bilingual(
                lang,
                "未列出的 SSO 用户与裸 IP 访问均为只读。",
                "Unlisted SSO users and direct-IP sessions are read-only.",
              )}
            </p>
          </div>
        </div>

        <form
          className="access-create access-create-permissions ra-users-form"
          id="raAccessUserForm"
          onSubmit={(e) => {
            e.preventDefault();
            const cleaned = newUsername.trim().toLowerCase();
            if (!cleaned) return;
            saveUserMutation.mutate({
              username: cleaned,
              role: newRole,
              intent_permission: newIntentPerm,
              annotation_role: newAnnotationRole,
              clearForm: true,
            });
          }}
        >
          <label>
            <span>{bilingual(lang, "用户名", "Username")}</span>
            <input
              id="accessUserName"
              maxLength={64}
              autoComplete="off"
              value={newUsername}
              placeholder={bilingual(lang, "例如 xuhaoxuan_i", "e.g. xuhaoxuan_i")}
              onChange={(e) => setNewUsername(e.target.value)}
            />
          </label>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "权限", "Role")}</span>
            <UiSelect
              id="accessUserRole"
              value={newRole}
              options={roleOptions}
              ariaLabel={bilingual(lang, "权限", "Role")}
              onChange={setNewRole}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "标注权限", "Annotation permission")}</span>
            <UiSelect
              id="accessIntentPermission"
              value={newIntentPerm}
              options={intentOptions}
              ariaLabel={bilingual(lang, "标注权限", "Annotation permission")}
              onChange={setNewIntentPerm}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "标注身份", "Annotation role")}</span>
            <UiSelect
              id="accessAnnotationRole"
              value={newAnnotationRole}
              options={annotationRoleOptions}
              ariaLabel={bilingual(lang, "标注身份", "Annotation role")}
              onChange={setNewAnnotationRole}
            />
          </div>
          <button
            className="button button-primary ra-primary-touch"
            type="submit"
            disabled={saveUserMutation.isPending || !newUsername.trim()}
          >
            {saveUserMutation.isPending
              ? bilingual(lang, "保存中…", "Saving…")
              : bilingual(lang, "添加用户", "Add user")}
          </button>
        </form>

        {feedback && (
          <p className={`ra-inline-feedback${feedback.isError ? " is-error" : ""}`} role="status">
            {feedback.text}
          </p>
        )}

        <div className="ra-users-filter-bar">
          <input
            type="search"
            value={search}
            placeholder={bilingual(lang, "按用户名筛选…", "Filter by username…")}
            aria-label={bilingual(lang, "按用户名筛选", "Filter by username")}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
              syncUrlPagination(1, pageSize);
            }}
          />
          <UiSelect
            value={roleFilter}
            options={roleFilterOptions}
            ariaLabel={bilingual(lang, "角色筛选", "Filter by role")}
            onChange={(val) => {
              setRoleFilter(val);
              setPage(1);
              syncUrlPagination(1, pageSize);
            }}
          />
        </div>

        <div className="access-list" id="raAccessUserList">
          {accessQuery.isLoading ? (
            <div className="no-asset">
              {bilingual(lang, "正在加载用户权限…", "Loading user access…")}
            </div>
          ) : accessQuery.isError ? (
            <div className="no-asset">
              {bilingual(lang, "读取用户权限失败，请刷新重试。", "Failed to load users.")}
            </div>
          ) : visibleUsers.length === 0 ? (
            <div className="no-asset">
              {bilingual(lang, "暂无匹配的用户记录。", "No matching users found.")}
            </div>
          ) : (
            visibleUsers.map((user) => {
              const draft = getDraft(user);
              return (
                <div
                  className="access-row access-role-row ra-user-edit-row"
                  key={user.username}
                  data-access-user={user.username}
                >
                  <div className="access-identity ra-user-meta">
                    <strong>{user.username}</strong>
                    <div className="ra-user-chips">
                      <StatusChip
                        label={
                          user.role === "admin"
                            ? bilingual(lang, "管理员", "Admin")
                            : bilingual(lang, "可写", "Writer")
                        }
                        tone={user.role === "admin" ? "ok" : "neutral"}
                      />
                    </div>
                    {user.updated_at && (
                      <small className="muted">{formatCstTime(user.updated_at, lang)}</small>
                    )}
                  </div>
                  <UiSelect
                    value={draft.role}
                    options={roleOptions}
                    ariaLabel={bilingual(
                      lang,
                      `${user.username} 的权限`,
                      `Role for ${user.username}`,
                    )}
                    onChange={(val) => updateDraft(user, { role: val })}
                  />
                  <UiSelect
                    value={draft.intent_permission}
                    options={intentOptions}
                    ariaLabel={bilingual(
                      lang,
                      `${user.username} 的标注权限`,
                      `Annotation permission for ${user.username}`,
                    )}
                    onChange={(val) => updateDraft(user, { intent_permission: val })}
                  />
                  <UiSelect
                    value={draft.annotation_role}
                    options={rowAnnotationRoleOptions}
                    ariaLabel={bilingual(
                      lang,
                      `${user.username} 的标注身份`,
                      `Annotation role for ${user.username}`,
                    )}
                    onChange={(val) => updateDraft(user, { annotation_role: val })}
                  />
                  <div className="access-row-actions">
                    <button
                      type="button"
                      className="button button-quiet"
                      disabled={savingUser === user.username}
                      onClick={() =>
                        saveUserMutation.mutate({
                          username: user.username,
                          role: draft.role,
                          intent_permission: draft.intent_permission,
                          annotation_role: draft.annotation_role,
                        })
                      }
                    >
                      {savingUser === user.username
                        ? bilingual(lang, "保存中…", "Saving…")
                        : bilingual(lang, "保存", "Save")}
                    </button>
                    <button
                      type="button"
                      className="button button-danger"
                      disabled={deletingUser === user.username}
                      onClick={() => setConfirmRemoveUser(user.username)}
                    >
                      {bilingual(lang, "移除", "Remove")}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <Pagination
          page={clampedPage}
          pageSize={pageSize}
          total={filteredUsers.length}
          lang={lang}
          loading={accessQuery.isFetching}
          ariaLabel={bilingual(lang, "用户权限列表分页", "User access pagination")}
          onPageChange={handlePageChange}
          onPageSizeChange={handlePageSizeChange}
        />
      </section>

      <section className="access-panel">
        <div className="access-heading">
          <div>
            <span className="eyebrow">DCHAT DIRECTORY</span>
            <h2>{bilingual(lang, "可 @ 人员", "Mention directory")}</h2>
            <p>
              {bilingual(
                lang,
                "只控制评论中可被 @ 并接收 DChat 的人员，不授予看板写入或管理员权限。",
                "Controls mention and DChat eligibility only; it does not grant Dashboard write or admin access.",
              )}
            </p>
          </div>
        </div>

        <form
          className="access-create ra-mention-form"
          id="raMentionUserForm"
          onSubmit={(e) => {
            e.preventDefault();
            const cleaned = newMentionUsername.trim().toLowerCase();
            if (!cleaned) return;
            saveMentionMutation.mutate({ username: cleaned, enabled: true, clearForm: true });
          }}
        >
          <label>
            <span>{bilingual(lang, "LDAP 用户名", "LDAP username")}</span>
            <input
              id="mentionUserName"
              maxLength={64}
              autoComplete="off"
              value={newMentionUsername}
              placeholder={bilingual(lang, "例如 jasperchen", "e.g. jasperchen")}
              onChange={(e) => setNewMentionUsername(e.target.value)}
            />
          </label>
          <button
            className="button button-primary ra-primary-touch"
            type="submit"
            disabled={saveMentionMutation.isPending || !newMentionUsername.trim()}
          >
            {saveMentionMutation.isPending
              ? bilingual(lang, "保存中…", "Saving…")
              : bilingual(lang, "添加可 @ 人员", "Add mention user")}
          </button>
        </form>

        {mentionFeedback && (
          <p
            className={`ra-inline-feedback${mentionFeedback.isError ? " is-error" : ""}`}
            role="status"
          >
            {mentionFeedback.text}
          </p>
        )}

        <div className="ra-users-filter-bar is-single">
          <input
            type="search"
            value={mentionSearch}
            placeholder={bilingual(lang, "筛选可 @ 人员…", "Filter mention directory…")}
            aria-label={bilingual(lang, "筛选可 @ 人员", "Filter mention directory")}
            onChange={(e) => {
              setMentionSearch(e.target.value);
              setMentionPage(1);
            }}
          />
        </div>

        <div className="access-list" id="raMentionUserList">
          {mentionQuery.isLoading ? (
            <div className="no-asset">
              {bilingual(lang, "正在加载可 @ 人员…", "Loading mention directory…")}
            </div>
          ) : mentionQuery.isError ? (
            <div className="no-asset">
              {bilingual(lang, "读取可 @ 人员失败。", "Failed to load mention directory.")}
            </div>
          ) : visibleMentions.length === 0 ? (
            <div className="no-asset">
              {bilingual(lang, "暂无匹配的可 @ 人员。", "No matching mention users.")}
            </div>
          ) : (
            visibleMentions.map((m) => {
              const enabledVal =
                m.username in mentionDrafts ? mentionDrafts[m.username] : m.enabled !== false;
              return (
                <div
                  className="access-row ra-mention-row"
                  key={m.username}
                  data-mention-user={m.username}
                >
                  <div className="access-identity ra-user-meta">
                    <strong>{m.display_name || m.username}</strong>
                    <small className="muted">
                      @{m.username} ·{" "}
                      {m.enabled !== false
                        ? bilingual(lang, "可被提及并接收 DChat", "Mentionable & DChat enabled")
                        : bilingual(lang, "已停用通知", "Notifications disabled")}
                    </small>
                  </div>
                  <label className="access-enabled-toggle">
                    <input
                      type="checkbox"
                      checked={enabledVal}
                      onChange={(e) =>
                        setMentionDrafts((prev) => ({
                          ...prev,
                          [m.username]: e.target.checked,
                        }))
                      }
                    />{" "}
                    <span>{bilingual(lang, "启用", "Enabled")}</span>
                  </label>
                  <div className="access-row-actions">
                    <button
                      type="button"
                      className="button button-quiet"
                      disabled={savingMention === m.username}
                      onClick={() =>
                        saveMentionMutation.mutate({ username: m.username, enabled: enabledVal })
                      }
                    >
                      {savingMention === m.username
                        ? bilingual(lang, "保存中…", "Saving…")
                        : bilingual(lang, "保存", "Save")}
                    </button>
                    <button
                      type="button"
                      className="button button-danger"
                      disabled={deletingMention === m.username}
                      onClick={() => setConfirmRemoveMention(m.username)}
                    >
                      {bilingual(lang, "移除", "Remove")}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <Pagination
          page={clampedMentionPage}
          pageSize={mentionPageSize}
          total={filteredMentions.length}
          lang={lang}
          loading={mentionQuery.isFetching}
          ariaLabel={bilingual(lang, "可 @ 人员列表分页", "Mention directory pagination")}
          onPageChange={setMentionPage}
          onPageSizeChange={(nextSize) => {
            setMentionPageSize(nextSize);
            setMentionPage(1);
          }}
        />
      </section>

      <ModalDialog
        open={Boolean(confirmRemoveUser)}
        title={bilingual(lang, "确认移除用户权限", "Confirm access removal")}
        lang={lang}
        onClose={() => {
          if (!deletingUser) setConfirmRemoveUser(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={Boolean(deletingUser)}
              onClick={() => setConfirmRemoveUser(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-danger ra-primary-touch"
              disabled={Boolean(deletingUser)}
              onClick={() => {
                if (confirmRemoveUser) deleteUserMutation.mutate(confirmRemoveUser);
              }}
            >
              {deletingUser
                ? bilingual(lang, "移除中…", "Removing…")
                : bilingual(lang, "确认移除", "Remove")}
            </button>
          </>
        }
      >
        <p className="ra-alloc-subtitle">
          {bilingual(
            lang,
            `确认移除 ${confirmRemoveUser || ""} 的看板权限？移除后该用户将变为只读权限。`,
            `Remove Dashboard access for ${confirmRemoveUser || ""}? The user will become read-only.`,
          )}
        </p>
      </ModalDialog>

      <ModalDialog
        open={Boolean(confirmRemoveMention)}
        title={bilingual(lang, "确认移除可 @ 人员", "Confirm mention removal")}
        lang={lang}
        onClose={() => {
          if (!deletingMention) setConfirmRemoveMention(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={Boolean(deletingMention)}
              onClick={() => setConfirmRemoveMention(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-danger ra-primary-touch"
              disabled={Boolean(deletingMention)}
              onClick={() => {
                if (confirmRemoveMention) deleteMentionMutation.mutate(confirmRemoveMention);
              }}
            >
              {deletingMention
                ? bilingual(lang, "移除中…", "Removing…")
                : bilingual(lang, "确认移除", "Remove")}
            </button>
          </>
        }
      >
        <p className="ra-alloc-subtitle">
          {bilingual(
            lang,
            `确认将 @${confirmRemoveMention || ""} 从可 @ 目录中移除？`,
            `Remove @${confirmRemoveMention || ""} from the mention directory?`,
          )}
        </p>
      </ModalDialog>
    </div>
  );
};
