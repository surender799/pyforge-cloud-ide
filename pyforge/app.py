import asyncio
from pathlib import Path
import uuid
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .workspace import Workspace, Conflict
from . import sandbox


class FileEdit(BaseModel):
    path: str = Field(max_length=200)
    content: str = Field(default="", max_length=100_000)
    revision: int = Field(default=0, ge=0)


class Commit(BaseModel):
    message: str = Field(min_length=1, max_length=300)


class Run(BaseModel):
    path: str = Field(default="main.py", max_length=200)


def same_origin(ws):
    origin = ws.headers.get("origin")
    return not origin or urlsplit(origin).netloc == ws.headers.get("host")


def create_app(root=".data/pyforge"):
    app = FastAPI(title="PyForge")
    workspace = Workspace(root)
    app.state.workspace = workspace
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")
    clients = {}

    async def broadcast(message):
        dead = []
        for ws in list(clients):
            try:
                await ws.send_json(message)
            except (RuntimeError, WebSocketDisconnect):
                dead.append(ws)
        for ws in dead:
            clients.pop(ws, None)

    @app.get("/")
    def home():
        return FileResponse(static / "index.html")

    @app.get("/api/files")
    def files():
        return workspace.files()

    @app.get("/api/file")
    def file(path: str):
        try:
            return workspace.get(path)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except KeyError:
            raise HTTPException(404, "File not found") from None

    @app.get("/api/history")
    def history(path: str):
        try:
            return workspace.history(path)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/files", status_code=201)
    async def save(edit: FileEdit):
        try:
            doc = workspace.save(edit.path, edit.content, edit.revision)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except Conflict as e:
            raise HTTPException(
                409, {"message": "Revision conflict", "current": e.current}
            ) from None
        await broadcast({"type": "saved", "document": doc, "peer": "api"})
        return doc

    @app.get("/api/git")
    def status():
        return workspace.status()

    @app.post("/api/commit")
    def commit(body: Commit):
        try:
            return workspace.commit(body.message)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/run")
    def execute(body: Run):
        try:
            workspace.get(body.path)
            if not body.path.endswith(".py"):
                raise ValueError("Select a Python file")
            with workspace.snapshot() as root:
                return sandbox.run(root, ["python", "-B", "-u", body.path])
        except KeyError:
            raise HTTPException(404, "File not found") from None
        except (ValueError, RuntimeError, OSError) as e:
            raise HTTPException(400, str(e)) from None

    @app.websocket("/ws")
    async def shared(ws: WebSocket):
        if not same_origin(ws):
            await ws.close(code=1008)
            return
        await ws.accept()
        peer = uuid.uuid4().hex[:8]
        clients[ws] = peer
        await ws.send_json({"type": "hello", "peer": peer})
        await broadcast({"type": "presence", "peers": list(clients.values())})
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > 110_000:
                    await ws.send_json(
                        {"type": "error", "message": "Message too large"}
                    )
                    continue
                import json

                try:
                    payload = json.loads(raw)
                    if payload.get("type") != "save":
                        continue
                    edit = FileEdit.model_validate(payload)
                    doc = workspace.save(edit.path, edit.content, edit.revision)
                    await broadcast({"type": "saved", "document": doc, "peer": peer})
                except Conflict as e:
                    await ws.send_json({"type": "conflict", "document": e.current})
                except (ValueError, TypeError, AttributeError) as e:
                    await ws.send_json({"type": "error", "message": str(e)})
        except WebSocketDisconnect:
            pass
        finally:
            clients.pop(ws, None)
            await broadcast({"type": "presence", "peers": list(clients.values())})

    @app.websocket("/terminal")
    async def terminal(ws: WebSocket):
        if not same_origin(ws):
            await ws.close(code=1008)
            return
        await ws.accept()
        name = "pyforge-terminal-" + uuid.uuid4().hex
        process = None
        try:
            with workspace.snapshot() as root:
                args = sandbox.command(root, name, ["sh"], interactive=True)
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                process.stdin.write(sandbox.payload(root))
                await process.stdin.drain()

                async def output():
                    sent = 0
                    while data := await process.stdout.read(4096):
                        sent += len(data)
                        if sent > 1_000_000:
                            break
                        await ws.send_text(data.decode(errors="replace"))

                async def input():
                    while True:
                        text = await ws.receive_text()
                        if len(text) > 4096:
                            raise ValueError("Command too long")
                        process.stdin.write(text.encode() + b"\n")
                        await process.stdin.drain()

                tasks = [asyncio.create_task(output()), asyncio.create_task(input())]
                try:
                    done, pending = await asyncio.wait(
                        tasks, timeout=300, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (WebSocketDisconnect, RuntimeError, OSError, ValueError):
            pass
        finally:
            if process:
                cleanup = await asyncio.create_subprocess_exec(
                    "docker",
                    "rm",
                    "-f",
                    name,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await cleanup.wait()
                if process.returncode is None:
                    await process.wait()
            try:
                await ws.close()
            except RuntimeError:
                pass

    return app
