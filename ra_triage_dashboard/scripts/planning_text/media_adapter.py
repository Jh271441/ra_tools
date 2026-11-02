"""Extend personal original-BEV entrypoints without editing its frozen executor."""
from pathlib import Path
import shlex


def install(controller, recovery):
    runner = Path(__file__).with_name('runner.py')
    local_wrapper = Path(__file__).with_name('local_fallback.py')
    original_command = controller.command
    def command(args, log, timeout=1800):
        args = list(args)
        if [str(x) for x in args[1:4]] == ['-m', 'ares_animation', 'run-orion']:
            args = [args[0], str(runner), *args[3:]]
        return original_command(args, log, timeout)
    controller.command = command
    native = recovery.subprocess
    class RecoveryProcess:
        def __getattr__(self, name):
            return getattr(native, name)
        def run(self, args, *rest, **kwargs):
            args = list(args)
            if args[:3] == ['tmux', 'new-session', '-d']:
                command = shlex.split(args[-1])
                if len(command) > 1 and command[1] == str(controller.ROOT/'tools/manual_sidecar/local_fallback.py'):
                    args[-1] = shlex.join([command[0], str(local_wrapper), *command[2:]])
            return native.run(args, *rest, **kwargs)
    recovery.subprocess = RecoveryProcess()
