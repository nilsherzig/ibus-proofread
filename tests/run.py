"""Run the suite with an owned display and a private session bus."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    read_fd, write_fd = os.pipe()
    with tempfile.TemporaryFile() as log:
        display = subprocess.Popen([
            "Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1024x768x24", "-nolisten", "tcp",
        ], pass_fds=(write_fd,), stdout=log, stderr=log)
        os.close(write_fd)
        try:
            with os.fdopen(read_fd) as pipe:
                number = pipe.readline().strip()
            if not number:
                raise RuntimeError("Virtual display failed to start")
            env = dict(os.environ, DISPLAY=":" + number, GDK_BACKEND="x11", GIO_USE_VFS="local",
                       GTK_IM_MODULE="simple", PYTHONPATH=str(ROOT), PROOFREAD_TEST_PRIVATE_BUS="1")
            # Each component gets its own process. Host GTK input modules must not
            # load a second libibus into the GI engine-test process.
            for pattern in ("test_core.py", "test_demo.py", "test_ibus.py"):
                result = subprocess.call([
                    "dbus-run-session", "--", "python", "-m", "unittest", "discover",
                    "-s", "tests", "-p", pattern, "-v",
                ], cwd=ROOT, env=env)
                if result:
                    return result
            return 0
        finally:
            display.terminate()
            display.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
