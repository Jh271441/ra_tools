/* Browser-local, actor/Issue-scoped discussion drafts. Image bytes stay in IndexedDB. */
const DISCUSSION_DRAFT_PREFIX = "ra-triage-discussion-draft-v1:";
const discussionDraftMemory = new Map();
let discussionDraftDatabase;

function discussionDraftActor() {
  return String(state.session?.username || "").trim().toLowerCase();
}
function discussionDraftKey(context) {
  return context.actor ? DISCUSSION_DRAFT_PREFIX + JSON.stringify([
    withBase(""), context.actor, context.kind,
    ...(context.kind === "intent" ? [context.intentDatasetId, context.intentCaseId] : [context.issueId]),
  ]) : "";
}
function discussionDraftId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
function discussionDraftSignature(draft) {
  return JSON.stringify([draft.body, draft.replyTo?.id || null, (draft.images || []).map(i => i.token)]);
}
function readDiscussionDraft(context) {
  if (!context.draftKey) return null;
  // The current tab owns its latest snapshot even if persistent writes fail
  // while older localStorage values remain readable. A null snapshot records
  // confirmed retirement when removing the persistent value is unavailable.
  const memory = discussionDraftMemory.get(context.draftKey);
  let stored;
  try { stored = JSON.parse(window.localStorage.getItem(context.draftKey)); } catch (_) {}
  const memoryTime = Number(memory?.draft?.savedAt ?? memory?.savedAt ?? 0);
  const draft = memory && (!stored || memoryTime >= Number(stored.savedAt || 0)) ? memory.draft : stored;
  return draft?.version === 1 && typeof draft.body === "string" && Array.isArray(draft.images)
    && draft.images.length <= 4 && Date.now() - draft.savedAt < 30 * 86400000 ? draft : null;
}
function discussionDraftImageStore(operation) {
  discussionDraftDatabase ||= new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") { reject(new Error("Draft image storage unavailable")); return; }
    const request = indexedDB.open("ra-triage-discussion-drafts", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("images");
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Draft image storage blocked"));
    request.onsuccess = () => resolve(request.result);
  });
  return discussionDraftDatabase.then(db => new Promise((resolve, reject) => {
    const transaction = db.transaction("images", "readwrite");
    const request = operation(transaction.objectStore("images"));
    transaction.oncomplete = () => resolve(request?.result);
    transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error("Draft image storage failed"));
  }));
}
function pruneDiscussionDrafts() {
  try {
    const storage = window.localStorage;
    const rows = [];
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i);
      if (!key?.startsWith(DISCUSSION_DRAFT_PREFIX)) continue;
      let value; try { value = JSON.parse(storage.getItem(key)); } catch (_) {}
      rows.push({key, time:Number(value?.savedAt || 0)});
    }
    rows.sort((a,b) => b.time - a.time).forEach((row,index) => {
      if (index < 40 && Date.now() - row.time < 30 * 86400000) return;
      storage.removeItem(row.key);
      const memory = discussionDraftMemory.get(row.key);
      if (Number(memory?.draft?.savedAt ?? memory?.savedAt ?? 0) <= row.time) discussionDraftMemory.delete(row.key);
      discussionDraftImageStore(store => store.delete(row.key)).catch(() => {});
    });
  } catch (_) { /* Browser storage may be disabled; the current tab keeps drafts. */ }
}

function persistAnalysisDiscussionDraft(context = state.analysisDiscussion) {
  if (!context?.draftKey || state.analysisDiscussion !== context || context.clearingSentDraft || context.status === "posted") return null;
  const textarea = $("#analysisDiscussionNote");
  if (!textarea) return null;
  const previous = readDiscussionDraft(context);
  const images = (context.pendingImages || []).map(item => ({token:item.token,
    name:item.file?.name || item.name || "", type:item.file?.type || item.type || "",
    size:item.file?.size || item.size || 0}));
  const draft = {version:1, body:textarea.value, replyTo:context.replyTo ? {id:context.replyTo.id,author:context.replyTo.author} : null,
    replyMentionPrefix:context.replyMentionPrefix || "", images, savedAt:Date.now(),
    selectionStart:textarea.selectionStart, selectionEnd:textarea.selectionEnd, scrollTop:textarea.scrollTop};
  if (context.committedDraftId && context.committedDraftId === context.draftId
      && discussionDraftSignature(draft) === context.committedDraftSignature) return null;
  const same = previous && discussionDraftSignature(previous) === discussionDraftSignature(draft);
  draft.id = same ? previous.id : discussionDraftId();
  context.draftId = draft.id;
  draft.imageId = previous && JSON.stringify(previous.images) === JSON.stringify(images) ? previous.imageId : discussionDraftId();
  if (context.submission) draft.submission = {id:context.submission.id,signature:context.submission.signature,uncertain:Boolean(context.submission.uncertain)};
  const retained = (context.pendingImages || []).map(({token,file,name,type,size}) => ({token,file,name,type,size}));
  discussionDraftMemory.delete(context.draftKey);
  discussionDraftMemory.set(context.draftKey, {draft, images:retained});
  try {
    if (draft.body || draft.replyTo || images.length) window.localStorage.setItem(context.draftKey, JSON.stringify(draft));
    else window.localStorage.removeItem(context.draftKey);
    context.draftStorageError = false;
  } catch (_) { context.draftStorageError = true; }
  discussionDraftMemory.get(context.draftKey).storageError = context.draftStorageError;
  if (!context.restoringDraftImages && (images.length || previous?.images.length) && draft.imageId !== previous?.imageId) {
    context.draftImageWrite = discussionDraftImageStore(store => {
      // A late image write cannot resurrect a sent or replaced draft.
      if (discussionDraftMemory.get(context.draftKey)?.draft?.imageId !== draft.imageId) return;
      return images.length ? store.put({imageId:draft.imageId,images:retained}, context.draftKey) : store.delete(context.draftKey);
    }).catch(() => {
      context.draftStorageError = true;
      const memory = discussionDraftMemory.get(context.draftKey);
      if (memory?.draft?.id === draft.id) memory.storageError = true;
    });
  }
  if (!previous) pruneDiscussionDrafts();
  while (discussionDraftMemory.size > 40) discussionDraftMemory.delete(discussionDraftMemory.keys().next().value);
  return draft;
}

function rememberDiscussionSubmission(context) {
  const draft = readDiscussionDraft(context);
  if (!draft || draft.id !== context.sentDraft?.id || !context.submission) return;
  draft.submission = {id:context.submission.id,signature:context.submission.signature,uncertain:Boolean(context.submission.uncertain)};
  const memory = discussionDraftMemory.get(context.draftKey);
  if (memory?.draft?.id === draft.id) memory.draft = draft;
  try { window.localStorage.setItem(context.draftKey, JSON.stringify(draft)); } catch (_) {}
}
function retireDiscussionDraft(context) {
  const sent = context.sentDraft;
  if (!sent) return;
  context.committedDraftId = sent.id;
  context.committedDraftSignature = discussionDraftSignature(sent);
  const active = state.analysisDiscussion;
  if (active && active !== context && active.draftKey === context.draftKey) persistAnalysisDiscussionDraft(active);
  const draft = readDiscussionDraft(context);
  if (draft?.id !== sent.id) return;
  try { window.localStorage.removeItem(context.draftKey); } catch (_) {}
  discussionDraftMemory.set(context.draftKey, {draft:null, images:[], savedAt:Date.now()});
  discussionDraftImageStore(store => {
    if (!readDiscussionDraft(context)?.images.length) return store.delete(context.draftKey);
  }).catch(() => {});
  if (active?.draftKey === context.draftKey && active.draftId === sent.id) {
    active.committedDraftId = sent.id;
    active.committedDraftSignature = discussionDraftSignature(sent);
    return active;
  }
}

async function restoreDiscussionDraftImages(context, draft) {
  if (!draft?.images.length) return;
  const memory = discussionDraftMemory.get(context.draftKey);
  let stored = memory?.draft?.imageId === draft.imageId && memory.images.every(image => image.file)
    ? {imageId:draft.imageId,images:memory.images} : null;
  context.restoringDraftImages = true;
  context.pendingImages = draft.images.map(item => ({...item,missing:true}));
  try { stored ||= await discussionDraftImageStore(store => store.get(context.draftKey)); } catch (_) {}
  if (state.analysisDiscussion !== context) return;
  context.pendingImages = context.pendingImages.map(item => {
    const image = stored?.imageId === draft.imageId ? stored.images.find(i => i.token === item.token && i.file) : null;
    return image ? {...item,file:image.file,missing:false,previewUrl:URL.createObjectURL(image.file)} : item;
  });
  context.restoringDraftImages = false;
  renderAnalysisDiscussionImages(); updateAnalysisDiscussionComposerAccess();
}
function restoreAnalysisDiscussionDraft(context) {
  const draft = readDiscussionDraft(context);
  if (!draft) return null;
  context.draftId = draft.id;
  const memory = discussionDraftMemory.get(context.draftKey);
  context.draftStorageError = Boolean(memory?.draft?.id === draft.id && memory.storageError);
  context.replyTo = draft.replyTo;
  context.replyMentionPrefix = draft.replyMentionPrefix;
  context.submission = draft.submission;
  const textarea = $("#analysisDiscussionNote");
  textarea.value = draft.body;
  textarea.setSelectionRange?.(draft.selectionStart ?? draft.body.length, draft.selectionEnd ?? draft.body.length);
  textarea.scrollTop = draft.scrollTop || 0;
  return draft;
}
