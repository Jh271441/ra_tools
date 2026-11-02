"""Original BEV local fallback, retaining its claim, admission and validation."""
from pathlib import Path
import sys

sys.path.insert(0, '/volume/home/workspace/ra_auto_triage')
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.manual_sidecar import local_fallback
from ra_triage_dashboard.scripts.planning_text.runner import take_version_context


def main():
    context = take_version_context()
    native = local_fallback.subprocess
    runner = Path(__file__).with_name('runner.py')
    class LocalProcess:
        def __getattr__(self, name):
            return getattr(native, name)
        def Popen(self, args, *rest, **kwargs):
            if list(args[1:4]) == ['-m', 'ares_animation', 'run-local']:
                args = [args[0], str(runner), *args[3:]]
                if context is not None:
                    args += ['--planning-version-context', str(context)]
            return native.Popen(args, *rest, **kwargs)
    local_fallback.subprocess = LocalProcess()
    return local_fallback.main()


if __name__ == '__main__':
    main()
