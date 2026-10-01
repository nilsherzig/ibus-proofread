"""Own a loopback-only llama.cpp server and a pinned, cached GGUF download."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.request

REPO = "unsloth/gemma-4-E2B-it-GGUF"
REVISION = "0314792d7f1f7e229411f620751375812bb9faf2"
FILENAME = "gemma-4-E2B-it-Q4_K_M.gguf"


def model_path():
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return root / "ibus-proofread" / REVISION / FILENAME


def download():
    path = model_path()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, partial = tempfile.mkstemp(dir=path.parent, suffix=".partial")
    os.close(fd)
    try:
        subprocess.run([
            "curl", "--fail", "--location", "--retry", "3", "--output", partial,
            f"https://huggingface.co/{REPO}/resolve/{REVISION}/{FILENAME}",
        ], check=True)
        with open(partial, "rb") as model:
            if model.read(4) != b"GGUF":
                raise ValueError("Download is not a GGUF model")
        os.replace(partial, path)
    finally:
        if os.path.exists(partial):
            os.unlink(partial)
    return path


@contextmanager
def server(model, binary="llama-server"):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    key = secrets.token_hex(32)
    url = f"http://127.0.0.1:{port}"
    # Temporary log: never retain prompts or generated text on disk.
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([
            binary, "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
            "--api-key", key, "-ngl", "99", "-c", "4096", "--parallel", "1",
            "--jinja", "--reasoning", "off", "--no-webui",
        ], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError("llama-server exited:\n" + log.read().decode(errors="replace")[-6000:])
                try:
                    req = urllib.request.Request(url + "/health", headers={"Authorization": "Bearer " + key})
                    with urllib.request.urlopen(req, timeout=1) as response:
                        if json.load(response).get("status") == "ok":
                            break
                except (OSError, ValueError):
                    time.sleep(0.2)
            else:
                raise RuntimeError("Model startup timed out")
            yield url, key
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
