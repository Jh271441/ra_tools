import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ares_playwright.upload import upload_login_state


class UploadLoginStateTest(unittest.TestCase):
    @patch("ares_playwright.upload.subprocess.run")
    @patch("ares_playwright.upload.shutil.which", return_value="/usr/bin/tool")
    def test_upload_uses_temporary_path_and_atomic_move(self, _which, run):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "state.json"
            state_file.write_text('{"cookies":[{}],"origins":[]}', encoding="utf-8")

            target = upload_login_state(
                state_file,
                "cloud_server",
                "/tmp/ares_storage_state.json",
                batch_mode=True,
            )

        self.assertEqual(target, "cloud_server:/tmp/ares_storage_state.json")
        scp_command = run.call_args_list[0].args[0]
        ssh_command = run.call_args_list[1].args[0]
        self.assertIn(
            "cloud_server:/tmp/ares_storage_state.json.uploading", scp_command
        )
        self.assertIn("BatchMode=yes", scp_command)
        self.assertIn(
            "chmod 600 -- /tmp/ares_storage_state.json.uploading && "
            "mv -f -- /tmp/ares_storage_state.json.uploading "
            "/tmp/ares_storage_state.json",
            ssh_command,
        )
        self.assertEqual(
            run.call_args_list[0].kwargs, {"check": True, "timeout": 300}
        )
        self.assertEqual(
            run.call_args_list[1].kwargs, {"check": True, "timeout": 60}
        )


if __name__ == "__main__":
    unittest.main()
