"""Deployment guard tests: no network calls or service mutations."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from contextlib import ExitStack

spec = importlib.util.spec_from_file_location("deploy_cloud", Path(__file__).parents[1] / "scripts/deploy_cloud.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

class DeployTests(unittest.TestCase):
    def test_additive_migration_guard_accepts_only_new_safe_sql(self):
        path = "ra_triage_dashboard/migrations/postgres/036_safe.sql"
        safe = """BEGIN;
ALTER TABLE intent_case_comments
    ADD COLUMN IF NOT EXISTS mentions_json jsonb NOT NULL DEFAULT '[]'::jsonb;
CREATE TABLE IF NOT EXISTS intent_comment_notifications (id bigserial PRIMARY KEY);
CREATE INDEX IF NOT EXISTS idx_intent_comment_notifications
    ON intent_comment_notifications(id);
COMMIT;
"""
        d.validate_additive_migration_sql(path, safe)
        for unsafe in (
            "BEGIN; DROP TABLE intent_case_comments; COMMIT;",
            "BEGIN; ALTER TABLE intent_case_comments RENAME TO old_comments; COMMIT;",
            "BEGIN; UPDATE intent_case_comments SET body = ''; COMMIT;",
        ):
            with self.assertRaises(d.DeployError):
                d.validate_additive_migration_sql(path, unsafe)

        def git(*args, **_kwargs):
            if args[:2] == ("diff", "--name-only"):
                return path
            if args[:2] == ("diff", "--name-status"):
                return f"A\t{path}"
            if args[0] == "show":
                return safe
            raise AssertionError(args)

        with patch.object(d, "git", side_effect=git):
            with self.assertRaises(d.DeployError):
                d.migration_changes("old", "new")
            self.assertEqual(
                d.migration_changes("old", "new", allow_additive=True),
                [path],
            )

    def test_additive_migration_runs_verified_backup_before_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate"
            scripts = candidate / "ra_triage_dashboard/scripts"
            scripts.mkdir(parents=True)
            record = root / "record"
            record.mkdir()
            data = root / "data"
            backup_root = data / "postgres_backups"
            backup_root.mkdir(parents=True)
            backup = backup_root / "ra_triage_dashboard-20260913T120000Z.dump"
            backup.touch()
            calls = []

            def run(*args, **kwargs):
                calls.append(args)
                if args[0] == "bash" and Path(args[1]).name == "backup_cloud_postgres.sh":
                    return MagicMock(stdout=f"{backup}\n".encode())
                if args[0] == d.PYTHON:
                    return MagicMock(stdout=b"36\n")
                return MagicMock(stdout=b"")

            with patch.object(d, "run", side_effect=run):
                result = d.apply_additive_migrations(
                    candidate,
                    {"DASHBOARD_DATA_DIR": str(data)},
                    ["ra_triage_dashboard/migrations/postgres/036_safe.sql"],
                    record,
                    35,
                )

            self.assertEqual(result, (str(backup.resolve()), 36))
            self.assertEqual(Path(calls[0][1]).name, "backup_cloud_postgres.sh")
            self.assertEqual(Path(calls[1][1]).name, "verify_cloud_postgres_backup.sh")
            self.assertEqual(calls[2][0], d.PYTHON)

    def test_gray_isolates_database_and_all_writers(self):
        env = {k: "true" for k in d.OFF}
        env.update(DASHBOARD_DATA_DIR="/production", DASHBOARD_DATABASE_URL_FILE="/production/postgres_url",
                   DASHBOARD_RA_MODEL_PROFILE_PATH=str(d.REPO / "ra_triage_dashboard/config/model_profiles.json"))
        result = d.gray_env(env, Path("/candidate"), Path("/isolated"), "a" * 40)
        self.assertEqual(result["DASHBOARD_DATABASE_URL"], "sqlite:////isolated/triage.sqlite3")
        self.assertEqual(result["DASHBOARD_DATABASE_URL_FILE"], "")
        self.assertEqual(result["DASHBOARD_RA_MODEL_PROFILE_PATH"], "/candidate/ra_triage_dashboard/config/model_profiles.json")
        self.assertTrue(all(result[k] == "false" for k in d.OFF))
        self.assertEqual(env["DASHBOARD_DATA_DIR"], "/production")

    def test_credentials_are_file_only(self):
        for key in ("DASHBOARD_DATABASE_URL", "DASHBOARD_API_KEY", "DASHBOARD_SECRET"):
            with self.assertRaises(d.DeployError):
                d.capture_env({"DASHBOARD_DATABASE_URL_FILE": "/db", key: "secret"})
        env = d.capture_env({"DASHBOARD_DATABASE_URL_FILE": "/db", "DASHBOARD_RA_MODEL_API_KEY_FILE": "/key", "UNRELATED_SECRET": "secret"})
        self.assertNotIn("UNRELATED_SECRET", env)
        self.assertEqual(env["DASHBOARD_RA_MODEL_API_KEY_FILE"], "/key")

    def test_runtime_policy_is_preserved(self):
        env = {"DASHBOARD_DATABASE_URL_FILE": "/db", "DASHBOARD_BASE_PATH": "/manual", "DASHBOARD_DEPLOYMENT_MODE": "development", "DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED": "true"}
        self.assertEqual(d.capture_env(env), env)

    def test_health_rejects_wrong_version_backend_and_writers(self):
        health = dict(ok=True, build_commit="a"*40, storage="sqlite-mvp", trail_attribute_write_enabled=False,
                      trail_attribute_review_write_enabled=False, batch_prediction_enabled=False, autotriage_push_enabled=False)
        d.check_health(health, "a"*40, "sqlite")
        for changes in ({"build_commit": "b"*40}, {"storage": "postgresql"}, {"batch_prediction_enabled": True}, {"ok": False}):
            with self.assertRaises(d.DeployError):
                d.check_health(dict(health, **changes), "a"*40, "sqlite")

    def test_lock_excludes_parallel_deployments(self):
        with tempfile.TemporaryDirectory() as temp:
            with d.deployment_lock(Path(temp)):
                with self.assertRaises(d.DeployError):
                    with d.deployment_lock(Path(temp)):
                        pass
            with d.deployment_lock(Path(temp)):
                pass

    def test_record_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"result.json"
            d.save(path, {"status": "ok"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {"status": "ok"})

    def test_cleanup_retains_latest_two_failed_and_busy(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp); folders=[]
            for i in range(5):
                folder=state/"releases"/str(i); folder.mkdir(parents=True)
                for name in ("candidate","rollback","gray-data"): (folder/name).mkdir()
                d.save(folder/"result.json", {"status": "failed" if i==4 else "success", "candidate": str(folder/"candidate"), "rollback": str(folder/"rollback")})
                folders.append(folder)
            removed=[]
            def remove(*args, **kwargs):
                path=Path(args[-1]); removed.append(path); path.rmdir()
            with patch.object(d,"git",return_value=""), patch.object(d,"in_use",side_effect=lambda path: str(path).startswith(str(folders[1]))), patch.object(d,"run",side_effect=remove):
                d.cleanup(state,folders[3])
            self.assertEqual(set(removed),{folders[0]/"candidate",folders[0]/"rollback"})
            self.assertFalse((folders[0]/"gray-data").exists())
            for folder in folders[1:]: self.assertTrue((folder/"candidate").exists())

    def test_cleanup_preserves_noncache_ignored_files(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)
            for i in range(3):
                folder=state/"releases"/str(i); folder.mkdir(parents=True)
                for name in ("candidate","rollback"): (folder/name).mkdir()
                d.save(folder/"result.json",{"status":"success","candidate":str(folder/"candidate"),"rollback":str(folder/"rollback")})
            def git(*args,**kwargs): return "local.sqlite3" if args[0]=="ls-files" else ""
            with patch.object(d,"git",side_effect=git),patch.object(d,"in_use",return_value=False),patch.object(d,"run") as run:
                d.cleanup(state,folder)
            run.assert_not_called()

    def test_zombie_process_counts_as_stopped(self):
        with patch.object(d.Path,"read_text",return_value="27205 (python3) Z 17766 27205"):
            self.assertFalse(d.process_alive(27205))
        with patch.object(d.Path,"read_text",return_value="27205 (python3) S 17766 27205"):
            self.assertTrue(d.process_alive(27205))
        with patch.object(d.Path,"read_text",side_effect=FileNotFoundError):
            self.assertFalse(d.process_alive(27205))

    def test_stop_waits_for_tmux_session_cleanup(self):
        with patch.object(d,"git_pane_pid",return_value=123), patch.object(d.os,"kill"), patch.object(d,"process_alive",return_value=False), patch.object(d.subprocess,"run",side_effect=[type("R",(),{"returncode":0})(),type("R",(),{"returncode":1})()]), patch.object(d.time,"sleep") as sleep:
            d.stop_production(123)
            sleep.assert_called_once_with(0.1)

    def test_stop_refuses_changed_process(self):
        with patch.object(d,"git_pane_pid",return_value=456),patch.object(d.os,"kill") as kill:
            with self.assertRaises(d.DeployError): d.stop_production(123)
            kill.assert_not_called()

    def simulate_release(self, fail_tests=False, fail_production=False):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            base=Path(temp); repo=base/"repo"; repo.mkdir(); python=base/"python"; python.touch()
            env={"DASHBOARD_DATABASE_URL_FILE":"/db", "DASHBOARD_DATA_DIR":str(base/"data")}
            target="a"*40; old="b"*40
            stack.enter_context(patch.object(d,"REPO",repo))
            stack.enter_context(patch.object(d,"STATE",base/"state"))
            stack.enter_context(patch.object(d,"PYTHON",python))
            stack.enter_context(patch.object(d.sys,"platform","linux"))
            def git(*args, **kwargs):
                if args[0]=="branch": return "master"
                if args[0]=="rev-parse": return target
                return ""
            stack.enter_context(patch.object(d,"git",side_effect=git))
            stack.enter_context(patch.object(d,"read_live",return_value=(11,env)))
            health={"ok":True,"build_commit":old,"storage":"postgresql"}
            stack.enter_context(patch.object(d,"get_json",return_value=health))
            stack.enter_context(patch.object(d.socket,"socket"))
            def run(*args,**kwargs):
                if fail_tests and "pytest" in args: raise subprocess.CalledProcessError(1,["pytest"])
                return MagicMock()
            stack.enter_context(patch.object(d,"run",side_effect=run))
            stack.enter_context(patch.object(d.subprocess,"Popen"))
            stack.enter_context(patch.object(d,"stop_child"))
            stack.enter_context(patch.object(d,"process_alive",return_value=False))
            stop=stack.enter_context(patch.object(d,"stop_production"))
            start=stack.enter_context(patch.object(d,"start_production"))
            stack.enter_context(patch.object(d,"git_pane_pid",return_value=22))
            stack.enter_context(patch.object(d,"cleanup",return_value=[]))
            def smoke(port,sha,storage):
                if fail_production and port==8785 and sha==target: raise d.DeployError("failed health")
                return dict(health,build_commit=sha,storage=storage)
            stack.enter_context(patch.object(d,"smoke",side_effect=smoke))
            if fail_tests or fail_production:
                with self.assertRaises((d.DeployError,subprocess.CalledProcessError)): d.deploy(target)
            else: d.deploy(target)
            record=json.loads(next((base/"state/releases").glob("*/result.json")).read_text())
            return stop.call_args_list,start.call_args_list,record

    def test_test_failure_never_stops_production(self):
        stops,starts,record=self.simulate_release(fail_tests=True)
        self.assertEqual(stops,[]); self.assertEqual(starts,[])
        self.assertEqual(record["status"],"failed")

    def test_failed_production_restores_previous_sha(self):
        stops,starts,record=self.simulate_release(fail_production=True)
        self.assertEqual([c.args[0] for c in stops],[11,22])
        self.assertEqual(starts[1].args[3],"b"*40)
        self.assertEqual(record["rollback_status"],"healthy")
        self.assertEqual(record["status"],"failed")

    def test_success_records_verified_target(self):
        stops,starts,record=self.simulate_release()
        self.assertEqual(len(stops),1); self.assertEqual(len(starts),1)
        self.assertEqual(record["target"],"a"*40)
        self.assertEqual(record["status"],"success")

    def test_rebase_only_changes_checkout_paths(self):
        env={"a":"/repo/app/file","b":"/repo-other/file","c":"/data/media"}
        self.assertEqual(d.rebase_env(env,"/repo","/gray"),{"a":"/gray/app/file","b":"/repo-other/file","c":"/data/media"})

if __name__ == "__main__": unittest.main()
