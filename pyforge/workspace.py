from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import json
import sqlite3
import subprocess
import tempfile
import threading


class Conflict(Exception):
    def __init__(self, current):
        self.current = current


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.tree = self.root / "workspace"
        self.tree.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript(
                "CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,content TEXT,revision INTEGER); CREATE TABLE IF NOT EXISTS history(path TEXT,revision INTEGER,content TEXT,PRIMARY KEY(path,revision));"
            )
        if not (self.tree / ".git").exists():
            self.git("init", "-b", "main")
            self.git("config", "user.name", "PyForge")
            self.git("config", "user.email", "pyforge@localhost")
        if not self.files():
            self.save("main.py", 'print("Hello from PyForge!")\n', 0)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / "files.db", timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def validate(path):
        p = PurePosixPath(path)
        if (
            not path
            or p.is_absolute()
            or "\\" in path
            or "\0" in path
            or any(x in ("", "..", ".") or x.startswith(".") for x in path.split("/"))
            or len(path) > 200
        ):
            raise ValueError("Use a relative, non-hidden workspace path")
        return p.as_posix()

    def files(self):
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute("SELECT path,revision FROM files ORDER BY path")
            ]

    def get(self, path):
        path = self.validate(path)
        with self.db() as db:
            row = db.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
            if not row:
                raise KeyError(path)
            return dict(row)

    def save(self, path, content, revision):
        path = self.validate(path)
        if len(content) > 100_000:
            raise ValueError("Files are limited to 100 KB")
        with self.lock, self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
            current = dict(row) if row else {"path": path, "content": "", "revision": 0}
            if current["revision"] != revision:
                raise Conflict(current)
            if (
                not row
                and db.execute("SELECT COUNT(*) FROM files").fetchone()[0] >= 100
            ):
                raise ValueError("Workspace is limited to 100 files")
            if not row:
                for other in db.execute("SELECT path FROM files"):
                    if path.startswith(other["path"] + "/") or other["path"].startswith(
                        path + "/"
                    ):
                        raise ValueError("A file cannot also be a directory")
            new = revision + 1
            db.execute(
                "INSERT INTO files VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET content=excluded.content,revision=excluded.revision",
                (path, content, new),
            )
            db.execute("INSERT INTO history VALUES(?,?,?)", (path, new, content))
            return {"path": path, "content": content, "revision": new}

    def history(self, path):
        path = self.validate(path)
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM history WHERE path=? ORDER BY revision DESC LIMIT 30",
                    (path,),
                )
            ]

    def materialize(self, destination):
        with self.db() as db:
            for row in db.execute("SELECT * FROM files"):
                path = Path(destination) / self.validate(row["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(row["content"])

    @contextmanager
    def snapshot(self):
        with tempfile.TemporaryDirectory(prefix="pyforge-") as directory:
            root = Path(directory)
            root.chmod(0o755)
            self.materialize(root)
            yield root

    def git(self, *args):
        r = subprocess.run(
            ["git", "-C", str(self.tree), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode:
            raise ValueError(
                r.stderr.strip() or r.stdout.strip() or "Git operation failed"
            )
        return r.stdout

    def status(self):
        with self.lock:
            self.materialize(self.tree)
            status = self.git("status", "--short")
            try:
                log = self.git("log", "-8", "--format=%h %s")
            except ValueError:
                log = ""
            return {"status": status, "log": log}

    def commit(self, message):
        if not message.strip():
            raise ValueError("Commit message is required")
        with self.lock:
            self.materialize(self.tree)
            self.git("add", "--all")
            self.git("commit", "-m", message)
            return self.status()
