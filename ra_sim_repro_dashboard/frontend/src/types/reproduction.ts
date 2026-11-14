export interface ReproductionSummary {
  policy: string; boundary_band_ms: number; eligible: number; evaluated: number;
  matched: number; pending: number; rate: number | null; covered_rate: number | null;
  statuses: Record<string, number>;
}
export interface ReproductionResult {
  status: string; matched: boolean | null; whole_window_triggered: boolean | null;
  first_event?: { request_offset_ms: number; publish_offset_ms?: number; timestamp_source: string };
}
