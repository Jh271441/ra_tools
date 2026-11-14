export interface SimulationProgress {
  state: string; priority?: string; total: number; completed: number; running: number; queued: number;
  failed: number; cancelled: number; unknown: number; finished: number; percent: number;
  max_concurrency: number; started_at: string | null; finished_at: string | null; observed_at: string;
  failures: { task_id: string; scenario_id: string; status: string }[];
}
export interface SimulationJob {
  job_id?: number | null; status: string; scenario_count?: number | null;
  backfill?: boolean; primary_execution?: boolean; evaluation_task_key?: string; archived?: boolean;
  url?: string | null; progress?: Partial<SimulationProgress> | null;
  progress_error?: string | null; error?: string | null;
}
