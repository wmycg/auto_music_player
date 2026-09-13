"""全量回归脚本:设置 offscreen 平台后执行 tests 全量发现。

复杂内联 shell 命令在本机易被破坏,环境变量统一经本脚本设置:
    .venv\\Scripts\\python.exe tests\\_run_offscreen_tests.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest


def main():
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    print(f"\npassed={result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)} "
          f"failed={len(result.failures)} errors={len(result.errors)} skipped={len(result.skipped)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())