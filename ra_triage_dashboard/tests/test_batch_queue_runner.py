from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from ra_triage_dashboard.app.batch_prediction_runner import BatchPredictionRunner


class _QueueDatabase:
    def __init__(self) -> None:
        self.jobs = {
            "job-1": {"id": "job-1", "status": "queued"},
            "job-2": {"id": "job-2", "status": "queued"},
        }

    def update_batch_prediction_job(self, job_id: str, **values):
        self.jobs[job_id].update(values)
        return dict(self.jobs[job_id])

    def next_queued_batch_prediction_job(self):
        return next(
            (
                dict(job)
                for job in self.jobs.values()
                if job["status"] == "queued"
            ),
            None,
        )


class BatchQueueRunnerTest(unittest.TestCase):
    def test_busy_runner_keeps_next_prediction_queued_then_starts_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(
                ra_auto_triage_root=root / "ra-source",
                batch_bag_cache_dir=root / "dashboard-data" / "batch-bags",
            )
            database = _QueueDatabase()
            runner = BatchPredictionRunner(settings, database)
            first_started = threading.Event()
            release_first = threading.Event()
            second_started = threading.Event()
            release_second = threading.Event()

            def predict(job_id: str) -> None:
                if job_id == "job-1":
                    first_started.set()
                    release_first.wait(timeout=2)
                else:
                    second_started.set()
                    release_second.wait(timeout=2)

            runner._predict = predict
            self.assertTrue(runner.launch_prediction(database.jobs["job-1"]))
            self.assertTrue(first_started.wait(timeout=1))
            self.assertTrue(runner.launch_prediction(database.jobs["job-2"]))
            self.assertEqual(database.jobs["job-2"]["status"], "queued")
            release_first.set()
            self.assertTrue(second_started.wait(timeout=1))
            self.assertEqual(database.jobs["job-2"]["status"], "running")
            release_second.set()
            runner.shutdown()


if __name__ == "__main__":
    unittest.main()
