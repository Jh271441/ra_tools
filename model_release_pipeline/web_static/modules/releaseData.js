import { DEFAULT_ACTIONS } from "./constants.js";

export function actionSpecs(payloadActions = []) {
  const byKey = Object.fromEntries(DEFAULT_ACTIONS.map((action) => [action.key, action]));
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
