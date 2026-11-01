const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture() {
  const storage = new Map();
  const tags = [{name: 'reviewTags', value: 'u_turn', checked: false}];
  const evidence = [{name: 'missingEvidence', value: 'camera', checked: false}];
  const element = (value = '') => ({value, dataset: {}, checked: false, disabled: false,
    setAttribute() {}, removeAttribute() {}, querySelector: () => null});
  const elements = Object.fromEntries(['expectedOutputInput', 'combinedCaseRationale', 'annotationNote',
    'modelReviewStatusInput', 'annotationAuthor', 'reviewExcludeInput', 'reviewSaveButton'].map(id => [id, element()]));
  const inputs = selector => selector.includes('reviewTags') ? tags.filter(item => !selector.includes(':checked') || item.checked)
    : selector.includes('missingEvidence') ? evidence.filter(item => !selector.includes(':checked') || item.checked) : [];
  elements.annotationForm = {...element(), dataset: {issueId: 'cn1'}, querySelectorAll: inputs};
  elements.reviewPane = {querySelectorAll: inputs};
  const model = {id: 101, model_run_id: 'run', work_split_id: 'task', author: 'alice',
    model_review_status: 'completed', note: 'Saved model reason', tags: [],
    created_at: '2026-01-01T00:00:00+08:00', missing_evidence: ['camera']};
  const revision = {id: 201, author: 'alice', expected_output: '误触发', tags: ['u_turn'],
    rationale: 'Saved Case rationale', is_excluded: true, created_at: model.created_at};
  const data = {issue_id: 'cn1', annotations: [model], label_state: {sources: [{revision_summaries: [revision]}]},
    review_assignment: {assigned: true, split_id: 'task', purpose: 'model_review',
      workflow_mode: 'model_review_and_case_label', model_run_id: 'run'}};
  const state = {activePage: 'review', selectedId: 'cn1', selectedCase: data, selectedRunId: 'run',
    reviewWorkSplitId: 'task', session: {username: 'alice', verified: true}, pendingReviewImages: [],
    reviewFormDirty: false, caseRationaleImages: new Map(), backgroundCaseUploads: new Map()};
  const context = {issue: {issue_id: 'cn1'}, campaign: {id: 'task', evaluation_run_id: 'run'},
    assigned: true, model_review: model, case_revision: revision, case_revision_id: revision.id,
    model_review_storage_id: model.id, label_state: data.label_state};
  elements.annotationAuthor.value = 'alice';
  const s = {state, URLSearchParams, Map, Set, console, document: {querySelectorAll: inputs},
    window: {localStorage: {getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)}},
    $: selector => elements[selector.slice(1)] || null,
    api: async () => ({context}), capturePageContext: () => ({}), isPageContextCurrent: () => true,
    hasDashboardWriteRole: () => true, uiText: zh => zh, escapeHtml: String,
    hasFocusedTextInput: node => node === s.focused, updateTagSummary() {}, updateEvidenceSummary() {},
    syncExpectedOutputFromTags() {}, enhanceNativeUiSelect() {}, renderReviewSummary() {},
    updateReviewHistory() {}, renderCaseRationaleImages() {}, updateReviewMentionComposer() {}, showToast() {}};
  vm.createContext(s);
  const root = process.env.REVIEW_HYDRATION_SOURCE_ROOT || path.join(__dirname, '../static/js');
  for (const file of ['review-draft.js', 'review-attachments.js', 'review-form.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), s, {filename: file});
  }
  Object.assign(s, {syncExpectedOutputFromTags() {}, renderReviewSummary() {}, renderCaseRationaleImages() {}});
  const saveDraft = fields => {
    elements.annotationForm._reviewDraftFields = new Set(fields);
    state.reviewFormDirty = true;
    s.persistReviewDraft(data);
  };
  return {s, state, data, context, elements, tags, evidence, storage, saveDraft};
}

async function delayedContextHydratesUntouchedFields() {
  const f = fixture();
  f.elements.annotationNote.value = 'New model note while Case context loads';
  f.saveDraft(['note']);
  await f.s.loadCombinedReviewContext(f.data);
  assert.equal(f.tags[0].checked, true, 'editing a model note must not hide saved Case tags');
  assert.equal(f.elements.expectedOutputInput.value, '误触发');
  assert.equal(f.elements.combinedCaseRationale.value, 'Saved Case rationale');
  assert.equal(f.elements.annotationNote.value, 'New model note while Case context loads');
  assert.equal(f.elements.reviewExcludeInput.checked, true, 'an unedited draft snapshot is not an exclusion edit');
  assert.equal(f.evidence[0].checked, true);
}

async function intentionalClearsAndFocusedTextSurvive() {
  const f = fixture();
  f.saveDraft(['tags', 'case_rationale', 'case_is_excluded']);
  await f.s.loadCombinedReviewContext(f.data);
  assert.equal(f.tags[0].checked, false);
  assert.equal(f.elements.combinedCaseRationale.value, '');
  assert.equal(f.elements.reviewExcludeInput.checked, false);
  assert.equal(f.elements.annotationNote.value, 'Saved model reason', 'Case edits must not hide saved model notes');
  const clean = fixture();
  clean.s.focused = clean.elements.combinedCaseRationale;
  clean.elements.combinedCaseRationale.value = 'IME preedit';
  await clean.s.loadCombinedReviewContext(clean.data);
  assert.equal(clean.elements.combinedCaseRationale.value, 'IME preedit');
  assert(clean.tags[0].checked);
}

async function savedDraftClearsAndNewerEditsSurvive() {
  for (const newerEdit of [false, true]) {
    const f = fixture();
    f.elements.expectedOutputInput.value = '误触发';
    f.elements.annotationNote.value = 'Submitted reason';
    f.tags[0].checked = true;
    f.saveDraft(['expected_output', 'tags', 'note']);
    f.state.combinedReviewContext = f.context;
    f.state.combinedReviewLoad = {key: f.s.combinedReviewContextKey(f.data), status: 'ready'};
    f.s.expectedOutputSelectionState = () => ({selectedValue: '误触发', conflictKind: ''});
    f.s.reviewSaveNavigationContext = () => ({});
    f.s.acknowledgeLocalChange = () => {};
    f.s.refreshReviewAfterSave = async () => {};
    f.s.renderReview = () => {throw new Error('saving must preserve the existing form nodes');};
    let resolve;
    f.s.submitCaseRationalePayload = () => new Promise(r => {resolve = r;});
    const saving = f.s.saveCombinedReview({submitter: f.elements.reviewSaveButton});
    if (newerEdit) {
      f.elements.annotationNote.value = 'Typed after submit';
      f.s.persistReviewDraft(f.data);
    }
    resolve({combined_review: {model_review: {...f.context.model_review, note: 'Submitted reason'}, label_state: f.data.label_state}});
    await saving;
    const draft = f.s.reviewDraftForCase(f.data);
    assert.equal(Boolean(draft), newerEdit, 'only edits newer than the successful submission may remain in storage');
    assert.equal(f.state.reviewFormDirty, newerEdit);
    if (newerEdit) assert.equal(f.elements.annotationNote.value, 'Typed after submit');
  }
}

function unrelatedDraftKeepsHistoricalTags() {
  const f = fixture();
  f.data.annotations = [{model_run_id: '', tags: ['u_turn']}];
  const draft = {tags: [], note: 'Only the model note changed', edited_fields: ['note']};
  const annotation = f.s.applyReviewDraft({}, draft);
  assert.deepEqual(Array.from(f.s.initialReviewTagsForCurrentRun(f.data, annotation, draft)), ['u_turn']);
  draft.edited_fields.push('tags');
  assert.deepEqual(Array.from(f.s.initialReviewTagsForCurrentRun(f.data, annotation, draft)), []);
}

(async () => {
  await delayedContextHydratesUntouchedFields();
  await intentionalClearsAndFocusedTextSurvive();
  await savedDraftClearsAndNewerEditsSurvive();
  unrelatedDraftKeepsHistoricalTags();
  console.log('Combined Review saved-field hydration, intentional clears, focus and save/draft races passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
