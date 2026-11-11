# -*- coding: utf-8 -*-
"""Win11 boot entry: preserve traceback to a text log; never opens hardware automatically."""
from pathlib import Path
import sys
import traceback
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
LOG = BASE / 'web_startup.log'

class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)
    def flush(self):
        for stream in self.streams:
            stream.flush()

def main():
    stdout, stderr = sys.stdout, sys.stderr
    try:
        with LOG.open('a', encoding='utf-8') as logfile:
            sys.stdout = Tee(stdout, logfile)
            sys.stderr = Tee(stderr, logfile)
            print('\n' + '='*64)
            print('STARTED', datetime.now().isoformat(timespec='seconds'))
            print('PYTHON', sys.version)
            print('EXECUTABLE', sys.executable)
            print('WORKING_DIR', Path.cwd())
            print('WEB_LOG', LOG)
            try:
                from native_web.server import main as serve
                serve(['--port', '8765', '--open-browser'])
                print('SERVER EXITED CLEANLY')
                return 0
            except BaseException:
                print('WEB SERVER FAILED:')
                traceback.print_exc()
                return 1
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
    except Exception:
        sys.stdout, sys.stderr = stdout, stderr
        traceback.print_exc()
        return 2
    finally:
        sys.stdout, sys.stderr = stdout, stderr

if __name__ == '__main__':
    raise SystemExit(main())
