export interface ScenarioLabelRow {
  issue_id: string;
  scenario_id: string;
  scenario_labels?: string[];
}

export interface ScenarioLabels {
  scenarioId: string;
  labels: string[] | null;
}

// A search can also match another issue's title or tags. Bind labels to both IDs.
// Missing or conflicting snapshots remain unknown, rather than an empty label set.
export function scenarioLabelsForIssue(
  issueId: string,
  scenarioIds: string[],
  rows: ScenarioLabelRow[],
): ScenarioLabels[] {
  return [...new Set(scenarioIds)].map((scenarioId) => {
    const matches = rows.filter(
      (row) => row.issue_id === issueId && row.scenario_id === scenarioId,
    );
    const values = matches.map((row) =>
      Array.isArray(row.scenario_labels) &&
      row.scenario_labels.every((value) => typeof value === 'string')
        ? [...new Set(row.scenario_labels)].sort()
        : null,
    );
    const labels =
      values.length > 0 &&
      values.every((value) => value !== null && JSON.stringify(value) === JSON.stringify(values[0]))
        ? values[0]
        : null;
    return { scenarioId, labels };
  });
}
