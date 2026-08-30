from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import run_with_voyager_env


def test_build_environment_parses_values_as_data(tmp_path, monkeypatch):
  env_file = tmp_path / "voyager.env"
  env_file.write_text(
      "\n".join([
          "PATH=/voyager/bin:/usr/bin",
          "PYTHONPATH=/voyager/python:/sdk/python",
          "LD_LIBRARY_PATH=/voyager/lib:/sdk/lib",
          "VOYAGER_ROOT=/voyager",
          "VOY_LIB_DIR=/voyager/lib",
          "VOY_CONFIG_DIR=/voyager/etc",
          "VOY_DATA_DIR=/voyager/share",
          "PLATFORM=GEN4",
          "LS_COLORS=rs=0:di=01;34:ln=01;36",
          "IGNORED_SECRET=do-not-forward",
      ]) + "\n",
      encoding="utf-8",
  )
  monkeypatch.setenv("EXISTING", "kept")
  monkeypatch.setenv("LS_COLORS", "original")

  environment = run_with_voyager_env.build_environment(env_file)

  assert environment["EXISTING"] == "kept"
  assert environment["PYTHONPATH"] == "/voyager/python:/sdk/python"
  assert environment["LS_COLORS"] == "original"
  assert "IGNORED_SECRET" not in environment


def test_read_env_file_accepts_export_prefix(tmp_path):
  env_file = tmp_path / "voyager.env"
  env_file.write_text("export VALUE=a=b;c\n", encoding="utf-8")

  assert run_with_voyager_env.read_env_file(env_file) == {"VALUE": "a=b;c"}
