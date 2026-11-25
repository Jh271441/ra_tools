import React, { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../../api/client";
import { bilingual, formatCstTime, UiLanguage, withWorkbenchBase } from "../../bridge/useWorkbenchBridge";
import { isTouchDevice, normalizeAssetUrl, showWorkbenchToast } from "../../features/review/reviewHelpers";
import { ModalDialog } from "../ui/ModalDialog";

export interface DiscussionAttachment {
  id: string;
  url?: string;
  filename?: string;
}

export interface DiscussionComment {
  id: number;
  author: string;
  author_verified?: boolean;
  body: string;
  created_at?: string;
  edited_at?: string;
  deleted?: boolean;
  version?: number;
  discussion_channel?: string;
  is_label_evidence?: boolean;
  reply_to_id?: number | null;
  reply_to_author?: string;
  reply_to_body?: string;
  reply_to_deleted?: boolean;
  attachments?: DiscussionAttachment[];
}

interface MentionUserEntry {
  username: string;
  display_name?: string;
  enabled?: boolean;
}

interface PendingImage {
  token: string;
  file: File;
  previewUrl: string;
}

export interface IssueDiscussionProps {
  open: boolean;
  kind?: "issue" | "intent";
  issueId: string;
  intentDatasetId?: string;
  intentCaseId?: string;
  reviewOrigin?: { model_run_id?: string; campaign_id?: string } | null;
  lang: UiLanguage;
  username: string;
  canWrite: boolean;
  isAdmin: boolean;
  onClose: () => void;
  onCountChange?: (count: number) => void;
}

function renderCommentInline(text: string, attachments: DiscussionAttachment[]): React.ReactNode[] {
  const map = new Map<string, string>();
  for (const att of attachments || []) {
    const resolved = normalizeAssetUrl(att.url || `/api/comment-attachments/${encodeURIComponent(att.id)}`);
    if (resolved) map.set(att.id, resolved);
  }
  const lines = String(text || "").split("\n");
  return lines.map((line, lineIdx) => {
    const imgMatch = line.match(/^!\[([^\]]*)\]\((attachment:([^)]+)|https?:\/\/[^)]+)\)$/);
    if (imgMatch) {
      const alt = imgMatch[1] || "image";
      const token = imgMatch[3];
      const src = token ? map.get(token) || "" : normalizeAssetUrl(imgMatch[2]);
      if (src) {
        return (
          <a key={lineIdx} className="comment-inline-image-link" href={src} target="_blank" rel="noreferrer">
            <img className="comment-inline-image" src={src} alt={alt} loading="lazy" />
          </a>
        );
      }
    }
    return (
      <p key={lineIdx} className="ra-comment-line">
        {line || "\u00A0"}
      </p>
    );
  });
}

export const IssueDiscussion: React.FC<IssueDiscussionProps> = ({
  open,
  kind = "issue",
  issueId,
  intentDatasetId = "",
  intentCaseId = "",
  reviewOrigin = null,
  lang,
  username,
  canWrite,
  isAdmin,
  onClose,
  onCountChange,
}) => {
  const queryClient = useQueryClient();
  const isIntent = kind === "intent" && Boolean(intentDatasetId && intentCaseId);
  const draftKey = `ra-discussion-draft:${kind}:${issueId}:${intentDatasetId}:${intentCaseId}:${username || "anon"}`;

  const [body, setBody] = useState("");
  const [previewMode, setPreviewMode] = useState(false);
  const [replyTo, setReplyTo] = useState<DiscussionComment | null>(null);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editBody, setEditBody] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<{ text: string; isError: boolean } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const queryPath = isIntent
    ? `/api/intent-datasets/${encodeURIComponent(intentDatasetId)}/cases/${encodeURIComponent(intentCaseId)}/comments`
    : `/api/cases/${encodeURIComponent(issueId)}/discussion`;

  const discussionQuery = useQuery<{ comments?: DiscussionComment[]; count?: number }>({
    queryKey: ["issue-discussion", kind, issueId, intentDatasetId, intentCaseId],
    queryFn: ({ signal }) =>
      apiRequest<{ comments?: DiscussionComment[]; count?: number }>(queryPath, { signal }),
    enabled: open && Boolean(issueId),
    staleTime: 10_000,
  });

  const mentionsQuery = useQuery<{ items?: MentionUserEntry[] }>({
    queryKey: ["mention-users"],
    queryFn: ({ signal }) => apiRequest<{ items?: MentionUserEntry[] }>("/api/mention-users", { signal }),
    enabled: open && canWrite,
    staleTime: 60_000,
  });

  const mentionUsers = useMemo(
    () => (mentionsQuery.data?.items || []).filter((u) => u.enabled !== false),
    [mentionsQuery.data],
  );

  // Restore draft on open
  useEffect(() => {
    if (!open) return;
    setFeedback(null);
    setPreviewMode(false);
    setEditingId(null);
    setDeletingId(null);
    try {
      const saved = localStorage.getItem(draftKey);
      if (saved) setBody(saved);
      else setBody("");
    } catch {
      setBody("");
    }
  }, [open, draftKey]);

  // Persist draft
  useEffect(() => {
    if (!open) return;
    try {
      if (body.trim()) localStorage.setItem(draftKey, body);
      else localStorage.removeItem(draftKey);
    } catch {
      // ignore storage errors
    }
  }, [body, open, draftKey]);

  // Cleanup preview object URLs on unmount or close
  useEffect(() => {
    if (!open && pendingImages.length) {
      pendingImages.forEach((img) => URL.revokeObjectURL(img.previewUrl));
      setPendingImages([]);
    }
  }, [open, pendingImages]);

  const comments = discussionQuery.data?.comments || [];
  useEffect(() => {
    if (discussionQuery.data) {
      onCountChange?.(Number(discussionQuery.data.count ?? comments.length));
    }
  }, [discussionQuery.data, comments.length, onCountChange]);

  const activeMentionToken = useMemo(() => {
    const match = body.match(/(?:^|\s)@([a-zA-Z0-9._-]{0,30})$/);
    return match ? match[1].toLowerCase() : null;
  }, [body]);

  const mentionSuggestions = useMemo(() => {
    if (activeMentionToken === null) return [];
    return mentionUsers
      .filter(
        (u) =>
          u.username.toLowerCase().includes(activeMentionToken) ||
          (u.display_name || "").toLowerCase().includes(activeMentionToken),
      )
      .slice(0, 6);
  }, [activeMentionToken, mentionUsers]);

  const insertMention = (targetUsername: string) => {
    setBody((prev) => prev.replace(/(^|\s)@[a-zA-Z0-9._-]{0,30}$/, `$1@${targetUsername} `));
    textareaRef.current?.focus();
  };

  const applyFormat = (format: "bold" | "italic" | "code" | "quote" | "list") => {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? start;
    const selected = body.slice(start, end);
    let next = "";
    if (format === "bold") next = `**${selected || bilingual(lang, "粗体文字", "bold")}**`;
    else if (format === "italic") next = `*${selected || bilingual(lang, "斜体文字", "italic")}*`;
    else if (format === "code") next = `\`${selected || "code"}\``;
    else if (format === "quote") {
      next = (selected || bilingual(lang, "引用内容", "quote"))
        .split("\n")
        .map((l) => `> ${l}`)
        .join("\n");
    } else {
      next = (selected || bilingual(lang, "列表项", "item"))
        .split("\n")
        .map((l) => `- ${l}`)
        .join("\n");
    }
    const merged = body.slice(0, start) + next + body.slice(end);
    setBody(merged);
    window.requestAnimationFrame(() => el.focus());
  };

  const addImages = (files: FileList | File[]) => {
    if (isIntent) {
      setFeedback({
        text: bilingual(lang, "意图标注讨论暂不支持图片附件。", "Intent discussion does not support image attachments."),
        isError: true,
      });
      return;
    }
    const allowed = new Set(["image/png", "image/jpeg", "image/webp"]);
    const nextList = [...pendingImages];
    let errText = "";
    for (const file of Array.from(files)) {
      if (nextList.length >= 4) {
        errText = bilingual(lang, "每条评论最多 4 张图片。", "Up to 4 images per comment.");
        break;
      }
      if (!allowed.has(file.type)) {
        errText = bilingual(lang, "仅支持 PNG、JPEG 或 WebP 图片。", "Only PNG, JPEG, and WebP images are supported.");
        continue;
      }
      if (file.size > 8 * 1024 * 1024) {
        errText = bilingual(lang, "单张图片不能超过 8 MB。", "Each image must be at most 8 MB.");
        continue;
      }
      const token = `pending-${typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
      const previewUrl = URL.createObjectURL(file);
      nextList.push({ token, file, previewUrl });
      const safeAlt = (file.name || "image").replace(/[\]\n]/g, "").slice(0, 60);
      setBody((prev) => `${prev}${prev && !prev.endsWith("\n") ? "\n" : ""}![${safeAlt}](attachment:${token})\n`);
    }
    setPendingImages(nextList);
    if (errText) setFeedback({ text: errText, isError: true });
  };

  const removePendingImage = (token: string) => {
    setPendingImages((prev) => {
      const target = prev.find((i) => i.token === token);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((i) => i.token !== token);
    });
    const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    setBody((prev) => prev.replace(new RegExp(`!?\\[[^\\]\\n]*\\]\\(attachment:${escaped}\\)\\n?`, "g"), ""));
  };

  const postMutation = useMutation({
    mutationFn: async () => {
      const trimmed = body.trim();
      if (!trimmed) throw new Error(bilingual(lang, "请输入讨论内容。", "Enter a comment."));
      const idempotencyKey =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `comment-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const payload: Record<string, unknown> = {
        body: trimmed,
        reply_to_id: replyTo?.id ?? null,
      };
      if (!isIntent && reviewOrigin?.model_run_id) {
        payload.review_context = reviewOrigin;
      }
      if (isIntent) {
        return apiRequest(queryPath, {
          method: "POST",
          body: payload,
        });
      }
      if (pendingImages.length > 0) {
        const form = new FormData();
        payload.attachment_tokens = pendingImages.map((i) => i.token);
        form.append("payload", JSON.stringify(payload));
        pendingImages.forEach((img, idx) => {
          form.append("attachments", img.file, img.file.name || `comment-${idx + 1}.png`);
        });
        return apiRequest(`/api/cases/${encodeURIComponent(issueId)}/discussion-with-attachments`, {
          method: "POST",
          body: form,
          headers: {
            "X-RA-Triage-Request": "comment-v1",
            "Idempotency-Key": idempotencyKey,
          },
        });
      }
      return apiRequest(queryPath, {
        method: "POST",
        body: payload,
        headers: { "Idempotency-Key": idempotencyKey },
      });
    },
    onSuccess: () => {
      setBody("");
      setReplyTo(null);
      pendingImages.forEach((i) => URL.revokeObjectURL(i.previewUrl));
      setPendingImages([]);
      setPreviewMode(false);
      try {
        localStorage.removeItem(draftKey);
      } catch {
        // ignore
      }
      setFeedback({ text: bilingual(lang, "评论已发表。", "Comment posted."), isError: false });
      void queryClient.invalidateQueries({
        queryKey: ["issue-discussion", kind, issueId, intentDatasetId, intentCaseId],
      });
    },
    onError: (err) => {
      setFeedback({
        text: err instanceof Error ? err.message : bilingual(lang, "发表失败，草稿已保留。", "Failed to post; draft retained."),
        isError: true,
      });
    },
  });

  const editDeleteMutation = useMutation({
    mutationFn: async (args: { id: number; mode: "edit" | "delete"; version: number; nextBody?: string }) => {
      const path = isIntent
        ? `/api/intent-datasets/${encodeURIComponent(intentDatasetId)}/cases/${encodeURIComponent(intentCaseId)}/comments/${args.id}`
        : `/api/cases/${encodeURIComponent(issueId)}/comments/${args.id}`;
      return apiRequest(path, {
        method: args.mode === "edit" ? "PATCH" : "DELETE",
        body: {
          expected_version: args.version,
          ...(args.mode === "edit" ? { body: args.nextBody || "" } : {}),
        },
      });
    },
    onSuccess: (_, vars) => {
      setEditingId(null);
      setDeletingId(null);
      setFeedback({
        text:
          vars.mode === "edit"
            ? bilingual(lang, "评论已修改。", "Comment updated.")
            : bilingual(lang, "评论已删除。", "Comment deleted."),
        isError: false,
      });
      void queryClient.invalidateQueries({
        queryKey: ["issue-discussion", kind, issueId, intentDatasetId, intentCaseId],
      });
    },
    onError: (err) => {
      setFeedback({
        text: err instanceof Error ? err.message : bilingual(lang, "操作失败，请刷新重试。", "Operation failed."),
        isError: true,
      });
    },
  });

  const copyShareUrl = async (commentId: number) => {
    const path = isIntent
      ? `${withWorkbenchBase("/intent-labeling")}?dataset=${encodeURIComponent(intentDatasetId)}&case=${encodeURIComponent(intentCaseId)}&comments=1&comment=${commentId}`
      : `${withWorkbenchBase("/review")}?issue=${encodeURIComponent(issueId)}&comments=1&channel=case&comment=${commentId}`;
    const full = `${window.location.origin}${path}`;
    try {
      await navigator.clipboard.writeText(full);
      showWorkbenchToast(bilingual(lang, "评论链接已复制。", "Comment link copied."));
    } catch {
      showWorkbenchToast(bilingual(lang, "复制失败。", "Copy failed."), true);
    }
  };

  const canManageComment = (comment: DiscussionComment): boolean => {
    if (!canWrite || comment.deleted || comment.is_label_evidence) return false;
    if (isAdmin) return true;
    return Boolean(
      comment.author_verified &&
        username &&
        String(comment.author || "").toLowerCase() === username.toLowerCase(),
    );
  };

  return (
    <ModalDialog
      open={open}
      wide
      lang={lang}
      title={`${isIntent ? bilingual(lang, "意图标注讨论", "Intent discussion") : bilingual(lang, "问题讨论", "Issue discussion")} · ${issueId}`}
      onClose={onClose}
    >
      <div className="ra-discussion-root">
        <div className="ra-discussion-thread" role="list" aria-live="polite">
          {discussionQuery.isPending ? (
            <div className="comment-thread-empty">{bilingual(lang, "正在加载评论…", "Loading comments…")}</div>
          ) : discussionQuery.isError ? (
            <div className="comment-thread-empty">
              <span>{bilingual(lang, "讨论加载失败。", "Failed to load discussion.")}</span>{" "}
              <button type="button" className="text-link" onClick={() => void discussionQuery.refetch()}>
                {bilingual(lang, "重试", "Retry")}
              </button>
            </div>
          ) : comments.length === 0 ? (
            <div className="comment-thread-empty">
              {bilingual(lang, "还没有评论，可以发起第一条讨论。", "No comments yet. Start the discussion.")}
            </div>
          ) : (
            comments.map((comment) => {
              const isEditing = editingId === comment.id;
              const isDeleting = deletingId === comment.id;
              return (
                <article key={comment.id} className="comment-thread-item" role="listitem">
                  <div className="comment-thread-meta">
                    <strong>{comment.author || "unknown"}</strong>
                    <span>
                      {comment.author_verified ? `${bilingual(lang, "已验证", "Verified")} · ` : ""}
                      {formatCstTime(comment.created_at, lang)}
                      {comment.edited_at ? ` · ${bilingual(lang, "已编辑", "Edited")}` : ""}
                    </span>
                  </div>

                  {comment.reply_to_id && (
                    <div className="comment-reply-quote">
                      {bilingual(lang, "回复", "Reply to")} {comment.reply_to_author || "—"}:{" "}
                      {comment.reply_to_deleted
                        ? bilingual(lang, "原评论已删除", "Original comment deleted")
                        : String(comment.reply_to_body || "").slice(0, 120)}
                    </div>
                  )}

                  <div className="comment-thread-body">
                    {comment.deleted ? (
                      <em>{bilingual(lang, "此评论已删除", "This comment was deleted")}</em>
                    ) : (
                      renderCommentInline(comment.body, comment.attachments || [])
                    )}
                  </div>

                  <div className="comment-thread-actions">
                    <button
                      type="button"
                      className="analysis-discussion-link"
                      onClick={() => void copyShareUrl(comment.id)}
                    >
                      {bilingual(lang, "分享", "Share")}
                    </button>
                    {canWrite && !comment.deleted && (
                      <button
                        type="button"
                        className="analysis-discussion-link"
                        onClick={() => {
                          setReplyTo(comment);
                          textareaRef.current?.focus();
                        }}
                      >
                        {bilingual(lang, "回复", "Reply")}
                      </button>
                    )}
                    {canManageComment(comment) && (
                      <>
                        <button
                          type="button"
                          className="analysis-discussion-link"
                          onClick={() => {
                            setDeletingId(null);
                            setEditingId(comment.id);
                            setEditBody(comment.body || "");
                          }}
                        >
                          {bilingual(lang, "编辑", "Edit")}
                        </button>
                        <button
                          type="button"
                          className="analysis-discussion-link"
                          onClick={() => {
                            setEditingId(null);
                            setDeletingId(comment.id);
                          }}
                        >
                          {bilingual(lang, "删除", "Delete")}
                        </button>
                      </>
                    )}
                  </div>

                  {isEditing && (
                    <div className="comment-edit-panel">
                      <textarea
                        rows={3}
                        maxLength={3500}
                        value={editBody}
                        onChange={(e) => setEditBody(e.target.value)}
                      />
                      <div className="comment-edit-actions">
                        <button type="button" className="button button-quiet" onClick={() => setEditingId(null)}>
                          {bilingual(lang, "取消", "Cancel")}
                        </button>
                        <button
                          type="button"
                          className="button button-primary"
                          disabled={editDeleteMutation.isPending || !editBody.trim()}
                          onClick={() =>
                            editDeleteMutation.mutate({
                              id: comment.id,
                              mode: "edit",
                              version: Number(comment.version || 1),
                              nextBody: editBody,
                            })
                          }
                        >
                          {bilingual(lang, "保存修改", "Save changes")}
                        </button>
                      </div>
                    </div>
                  )}

                  {isDeleting && (
                    <div className="comment-edit-panel">
                      <p>
                        {bilingual(
                          lang,
                          "确认删除这条评论？将保留删除占位与已有回复。",
                          "Delete this comment? A placeholder and existing replies remain.",
                        )}
                      </p>
                      <div className="comment-edit-actions">
                        <button type="button" className="button button-quiet" onClick={() => setDeletingId(null)}>
                          {bilingual(lang, "取消", "Cancel")}
                        </button>
                        <button
                          type="button"
                          className="button button-danger"
                          disabled={editDeleteMutation.isPending}
                          onClick={() =>
                            editDeleteMutation.mutate({
                              id: comment.id,
                              mode: "delete",
                              version: Number(comment.version || 1),
                            })
                          }
                        >
                          {bilingual(lang, "确认删除", "Delete comment")}
                        </button>
                      </div>
                    </div>
                  )}
                </article>
              );
            })
          )}
        </div>

        {feedback && (
          <p className={`discussion-notice discussion-submit-status${feedback.isError ? " is-error" : ""}`} role="status">
            {feedback.text}
          </p>
        )}

        {canWrite && (
          <form
            className="ra-discussion-composer"
            onSubmit={(e) => {
              e.preventDefault();
              postMutation.mutate();
            }}
          >
            {replyTo && (
              <div className="comment-reply-context">
                <span>
                  {bilingual(lang, "正在回复", "Replying to")} <strong>{replyTo.author}</strong>
                </span>
                <button type="button" className="button button-quiet" onClick={() => setReplyTo(null)}>
                  {bilingual(lang, "取消回复", "Cancel reply")}
                </button>
              </div>
            )}

            <div className="ra-discussion-toolbar">
              <button type="button" className="button button-quiet" onClick={() => applyFormat("bold")}>
                B
              </button>
              <button type="button" className="button button-quiet" onClick={() => applyFormat("italic")}>
                I
              </button>
              <button type="button" className="button button-quiet" onClick={() => applyFormat("code")}>
                {"</>"}
              </button>
              <button type="button" className="button button-quiet" onClick={() => applyFormat("quote")}>
                “
              </button>
              <button type="button" className="button button-quiet" onClick={() => applyFormat("list")}>
                •
              </button>
              {!isIntent && (
                <>
                  <button
                    type="button"
                    className="button button-quiet"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {bilingual(lang, "添加图片", "Add image")}
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    multiple
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files) addImages(e.target.files);
                      e.target.value = "";
                    }}
                  />
                </>
              )}
              <button
                type="button"
                className="button button-quiet"
                onClick={() => setPreviewMode((p) => !p)}
              >
                {previewMode ? bilingual(lang, "继续编辑", "Edit") : bilingual(lang, "预览", "Preview")}
              </button>
            </div>

            {previewMode ? (
              <div className="comment-preview-surface">
                {body.trim()
                  ? renderCommentInline(
                      body,
                      pendingImages.map((p) => ({ id: p.token, url: p.previewUrl })),
                    )
                  : bilingual(lang, "暂无可预览内容。", "Nothing to preview yet.")}
              </div>
            ) : (
              <textarea
                ref={textareaRef}
                rows={4}
                maxLength={3500}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                onPaste={(e) => {
                  const files = Array.from(e.clipboardData?.files || []).filter((f) =>
                    f.type.startsWith("image/"),
                  );
                  if (files.length) {
                    e.preventDefault();
                    addImages(files);
                  }
                }}
                onKeyDown={(e) => {
                  if (e.nativeEvent.isComposing || e.keyCode === 229) return;
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !isTouchDevice()) {
                    e.preventDefault();
                    if (!postMutation.isPending && body.trim()) postMutation.mutate();
                  }
                }}
                placeholder={bilingual(
                  lang,
                  "输入讨论内容，输入 @ 可通知同事（Ctrl/⌘+Enter 发表）…",
                  "Write a comment, type @ to mention a colleague (Ctrl/⌘+Enter to post)…",
                )}
              />
            )}

            {mentionSuggestions.length > 0 && !previewMode && (
              <div className="ra-mention-suggestions" role="listbox" aria-label={bilingual(lang, "选择提及人员", "Mention suggestions")}>
                {mentionSuggestions.map((u) => (
                  <button
                    key={u.username}
                    type="button"
                    className="button button-quiet"
                    onClick={() => insertMention(u.username)}
                  >
                    @{u.username}
                    {u.display_name && u.display_name !== u.username ? ` · ${u.display_name}` : ""}
                  </button>
                ))}
              </div>
            )}

            {pendingImages.length > 0 && (
              <div className="ra-pending-images">
                {pendingImages.map((img) => (
                  <div key={img.token} className="comment-pending-image">
                    <img src={img.previewUrl} alt={img.file.name} />
                    <span>{img.file.name}</span>
                    <button
                      type="button"
                      aria-label={bilingual(lang, "移除图片", "Remove image")}
                      onClick={() => removePendingImage(img.token)}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="ra-discussion-footer">
              <small className="muted">
                {bilingual(lang, "草稿自动保存在本机。", "Drafts are saved on this device.")}
              </small>
              <button
                type="submit"
                className="button button-primary ra-primary-touch"
                disabled={postMutation.isPending || !body.trim()}
              >
                {postMutation.isPending
                  ? bilingual(lang, "发表中…", "Posting…")
                  : bilingual(lang, "发表评论", "Post comment")}
              </button>
            </div>
          </form>
        )}
      </div>
    </ModalDialog>
  );
};
