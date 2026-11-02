"""Extend personal original-BEV entrypoints without editing its frozen executor."""
from pathlib import Path
import shlex


def install(controller, recovery):
    runner = Path(__file__).with_name('runner.py')
    local_wrapper = Path(__file__).with_name('local_fallback.py')
    current_context = None
    original_tick = recovery.tick
    def tick(work, *args, **kwargs):
        nonlocal current_context
        previous = current_context
        path = Path(work)/'version-context.json'
        current_context = path if path.is_file() else None
        try:
            return original_tick(work, *args, **kwargs)
        finally:
            current_context = previous
    recovery.tick = tick
    original_command = controller.command
    def command(args, log, timeout=1800):
        args = list(args)
        if [str(x) for x in args[1:4]] == ['-m', 'ares_animation', 'run-orion']:
            args = [args[0], str(runner), *args[3:]]
            if current_context is not None:
                args += ['--planning-version-context', str(current_context)]
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
                    command = [command[0], str(local_wrapper), *command[2:]]
                    if current_context is not None:
                        command += ['--planning-version-context', str(current_context)]
                    args[-1] = shlex.join(command)
            return native.run(args, *rest, **kwargs)
    recovery.subprocess = RecoveryProcess()
