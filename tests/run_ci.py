"""CI entry point: the whole suite, verbose, with a watchdog.

If anything hangs, faulthandler prints the stack of every thread and the run fails instead of sitting until the
runner's 6-hour limit.
"""
import faulthandler
import sys
import unittest

faulthandler.dump_traceback_later(int(sys.argv[1]) if len(sys.argv) > 1 else 1200, exit=True)
suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
