import shlex
import shutil
import subprocess
from pathlib import Path


def _ssh_options(batch_mode: bool) -> list[str]:
    options = ["-o", "ConnectTimeout=15"]
    if batch_mode:
        options.extend(["-o", "BatchMode=yes"])
    return options


def upload_login_state(
    state_file: Path,
    ssh_host: str,
    remote_state_path: str,
    batch_mode: bool = False,
) -> str:
    """Upload to a temporary remote file and atomically replace the final file."""
    state_file = state_file.resolve()
    if not state_file.is_file():
        raise FileNotFoundError(f"登录态文件不存在：{state_file}")
    if shutil.which("scp") is None or shutil.which("ssh") is None:
        raise RuntimeError("没有找到 scp 或 ssh 命令，请安装 OpenSSH Client")
    if not remote_state_path.startswith("/"):
        raise ValueError("远端登录态路径必须是绝对路径")

    try:
        state_file.chmod(0o600)
    except OSError as exc:
        print(f"[WARN] 无法设置本地文件权限为 600：{exc}")

    remote_tmp_path = f"{remote_state_path}.uploading"
    remote_target = f"{ssh_host}:{remote_state_path}"
    scp_command = ["scp", "-p", *_ssh_options(batch_mode)]
    scp_command.extend([str(state_file), f"{ssh_host}:{remote_tmp_path}"])

    print(f"[UPLOAD] 本地：{state_file}")
    print(f"[UPLOAD] 远端：{remote_target}")
    try:
        subprocess.run(scp_command, check=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SCP 上传超过 300 秒，已终止") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"SCP 上传登录态失败，退出码：{exc.returncode}") from exc

    remote_command = (
        f"chmod 600 -- {shlex.quote(remote_tmp_path)} && "
        f"mv -f -- {shlex.quote(remote_tmp_path)} "
        f"{shlex.quote(remote_state_path)}"
    )
    ssh_command = ["ssh", *_ssh_options(batch_mode), ssh_host, remote_command]
    try:
        subprocess.run(ssh_command, check=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("远端原子替换登录态时超时") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("无法设置远端权限并原子替换登录态") from exc

    print(f"[UPLOAD] 登录态上传完成：{remote_target}")
    return remote_target
