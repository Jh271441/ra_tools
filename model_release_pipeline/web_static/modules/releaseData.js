import { DEFAULT_ACTIONS } from "./constants.js";

export function actionSpecs(payloadActions = []) {
  const byKey = Object.fromEntries(DEFAULT_ACTIONS.map((action) => [action.key, action]));
  if (payloadActions && payloadActions.length) {
    const serverKeys = new Set(payloadActions.map((action) => action.key));
    for (const action of payloadActions) {
      byKey[action.key] = { ...(byKey[action.key] || {}), ...action };
    }
    return DEFAULT_ACTIONS
      .filter((action) => serverKeys.has(action.key))
      .map((action) => byKey[action.key])
      .concat(payloadActions.filter((action) => !DEFAULT_ACTIONS.some((known) => known.key === action.key)));
  }
  for (const action of payloadActions || []) {
    byKey[action.key] = { ...(byKey[action.key] || {}), ...action };
  }
  return Object.values(byKey);
}

export function draftPayload() {
  return {
    summary: {
      release_id: "New release draft",
      experiment_name: "Waiting for export to create release_id",
      selected_epoch: null,
      onnx_version: null,
      stage: "pending",
      status: "pending",
    },
    actions: actionSpecs(),
    timeline: [],
    logs: {},
  };
}
