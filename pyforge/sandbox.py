"""Disposable Docker execution with streamed snapshots, including remote Docker."""

from pathlib import Path
import io
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid

IMAGE = "python:3.13-alpine"
BOOTSTRAP = """
import io,os,sys,tarfile
def exact(n):
    chunks=[]
    while n:
        b=os.read(0,min(n,65536))
        if not b: raise RuntimeError('Incomplete workspace snapshot')
        chunks.append(b);n-=len(b)
    return b''.join(chunks)
size=int.from_bytes(exact(8),'big')
if size>20000000: raise RuntimeError('Snapshot too large')
raw=exact(size)
os.mkdir('/tmp/workspace')
with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
    archive.extractall('/tmp/workspace',filter='data')
os.chdir('/tmp/workspace')
os.execvp(sys.argv[1],sys.argv[1:])
"""


def payload(root):
    root = Path(root)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        total = 0
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("Workspace snapshots do not accept symlinks")
            if not path.is_file():
                continue
            content = path.read_bytes()
            total += len(content)
            if total > 18_000_000:
                raise ValueError("Workspace exceeds 18 MB")
            info = tarfile.TarInfo(path.relative_to(root).as_posix())
            info.size = len(content)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
    data = buf.getvalue()
    if len(data) > 20_000_000:
        raise ValueError("Snapshot exceeds 20 MB")
    return len(data).to_bytes(8, "big") + data


def command(root, name, argv, interactive=False):
    if not shutil.which("docker"):
        raise RuntimeError("Docker is required. Install Docker and pull " + IMAGE)
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "128m",
        "--cpus",
        "0.5",
        "--user",
        "65534:65534",
        "--tmpfs",
        "/tmp:rw,nosuid,noexec,size=32m",
        "-i",
        IMAGE,
        "python",
        "-u",
        "-c",
        BOOTSTRAP,
        *argv,
    ]


def run(root, argv, timeout=15):
    name = "pysystems-" + uuid.uuid4().hex
    args = command(root, name, argv)
    snapshot = payload(root)
    started = time.monotonic()
    reason = None
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT
        )

        def feed():
            try:
                proc.stdin.write(snapshot)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        try:
            while proc.poll() is None:
                if time.monotonic() - started > timeout:
                    reason = "Execution time limit exceeded"
                    break
                if log.tell() > 1_000_000:
                    reason = "Output limit exceeded"
                    break
                time.sleep(0.05)
        finally:
            if reason:
                subprocess.run(
                    ["docker", "rm", "-f", name], capture_output=True, timeout=20
                )
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            elif proc.poll() is None:
                proc.wait(timeout=5)
            feeder.join(timeout=2)
        log.seek(0)
        output = log.read(100_000).decode(errors="replace")
    return {
        "exit_code": proc.returncode,
        "output": output,
        "error": reason,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
