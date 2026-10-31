"""Server-side label sidecar, separate from simulation submission and browser sessions."""
import logging
import os
import signal
import threading
from app.services.label_cycle import CHECK_SECONDS, tick


def main():
    if os.getenv('LABEL_REFRESH_ENABLED') != '1':
        raise RuntimeError('Label refresh is disabled')
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig,lambda *_:stopping.set())
    while not stopping.is_set():
        try:
            tick()
        except Exception:
            logging.getLogger(__name__).exception('Label sidecar tick failed')
        stopping.wait(CHECK_SECONDS)


if __name__ == '__main__':
    main()
