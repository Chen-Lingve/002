import re
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .backup import create_backup
from .store import KBError, KnowledgeStore


TEXT_PREVIEW_LIMIT = 1024 * 1024
TEXT_PREVIEW_SUFFIXES = {".md", ".txt", ".json", ".csv", ".tsv", ".log", ".s2p", ".conv"}
BINARY_PREVIEW = {
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".pdf": ("application/pdf", b"%PDF-"),
}


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RecordWrite(StrictBody):
    record: dict
    actor: str = Field(min_length=1, max_length=80)
    publish: bool = False


class DraftWrite(RecordWrite):
    edit_token: int = Field(ge=1)


class RevisionWrite(StrictBody):
    from_version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=80)


class TransitionWrite(StrictBody):
    version: int = Field(ge=1)
    action: str
    edit_token: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=80)
    note: str = Field(max_length=4000)


def create_app(root):
    store = KnowledgeStore(root)
    app = FastAPI(title="RF Knowledge Workbench", docs_url="/api/docs", redoc_url=None)
    app.state.store = store
    app.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if (origin and origin != str(request.base_url).rstrip("/")
                    or request.headers.get("sec-fetch-site") == "cross-site"):
                return JSONResponse({"detail": "Foreign browser origin rejected."}, status_code=403)
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > 26 * 1024 * 1024):
                return JSONResponse({"detail": "Request too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(KBError)
    async def domain_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "schema_version": 1}

    @app.get("/api/stats")
    def stats():
        return store.stats()

    @app.get("/api/records")
    def records(query: str = "", kind: str | None = None, family: str | None = None,
                role: str | None = None, variant: str | None = None,
                status: str | None = None, include_drafts: bool = False,
                limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                case_type: str | None = None, rule_mode: str | None = None):
        return store.search(query, kind, family, role, variant, status, include_drafts, limit, offset,
                            case_type=case_type, rule_mode=rule_mode)

    @app.post("/api/records")
    def create(body: RecordWrite):
        return store.create_record(body.record, body.actor, publish=body.publish)

    @app.get("/api/records/{rid}")
    def record(rid: str, version: int | None = Query(None, ge=1)):
        return store.get_record(rid, version)

    @app.put("/api/records/{rid}/versions/{version}")
    def save(rid: str, version: int, body: DraftWrite):
        return store.save_draft(rid, version, body.record, body.edit_token, body.actor,
                                publish=body.publish)

    @app.get("/api/records/{rid}/versions")
    def versions(rid: str):
        return {"items": store.versions(rid)}

    @app.post("/api/records/{rid}/versions")
    def revision(rid: str, body: RevisionWrite):
        return store.new_version(rid, body.from_version, body.actor)

    @app.post("/api/records/{rid}/transition")
    def transition(rid: str, body: TransitionWrite):
        return store.transition(rid, body.version, body.action, body.edit_token, body.actor, body.note)

    @app.get("/api/records/{rid}/versions/{version}/snapshots")
    def snapshots(rid: str, version: int):
        return {"items": store.list_snapshots(rid, version)}

    @app.get("/api/records/{rid}/versions/{version}/snapshots/{content_hash}")
    def snapshot(rid: str, version: int, content_hash: str):
        return store.get_snapshot(rid, version, content_hash)

    @app.get("/api/records/{rid}/audit")
    def audit(rid: str):
        return {"items": store.audit(rid)}

    @app.get("/api/artifacts")
    def artifacts(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
        return store.list_artifacts(limit, offset)

    @app.post("/api/artifacts")
    async def upload(file: UploadFile = File()):
        data = await file.read(25 * 1024 * 1024 + 1)
        return store.add_artifact(file.filename, data)

    @app.get("/api/artifacts/{artifact_id}")
    def artifact(artifact_id: str):
        info = store.get_artifact(artifact_id)
        return Response(store.artifact_bytes(artifact_id), media_type="application/octet-stream",
                        headers={"Content-Disposition":
                                 "attachment; filename*=UTF-8''" + quote(info["filename"], safe="")})

    @app.get("/api/artifacts/{artifact_id}/preview")
    def artifact_preview(artifact_id: str):
        info = store.get_artifact(artifact_id)
        suffix = Path(info["filename"]).suffix.lower()
        unsupported = "此文件不支持在线预览，请下载原件。"
        if suffix not in TEXT_PREVIEW_SUFFIXES and suffix not in BINARY_PREVIEW:
            raise KBError(unsupported, 415)
        if suffix in TEXT_PREVIEW_SUFFIXES and info["byte_count"] > TEXT_PREVIEW_LIMIT:
            raise KBError("文本附件超过 1 MiB，请下载原件。", 413)
        content = store.artifact_bytes(artifact_id)
        if suffix in BINARY_PREVIEW:
            media_type, signature = BINARY_PREVIEW[suffix]
            if not content.startswith(signature):
                raise KBError(unsupported, 415)
        else:
            if b"\x00" in content:
                raise KBError(unsupported, 415)
            try:
                content = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise KBError("不是 UTF-8 文本，请下载原件。", 415) from None
            media_type = "text/plain"
        return Response(content, media_type=media_type, headers={
            "Content-Disposition": "inline; filename*=UTF-8''" + quote(info["filename"], safe=""),
        })

    @app.post("/api/evaluate")
    def evaluate(body: dict):
        return store.evaluate(body)

    @app.post("/api/context")
    def context(body: dict):
        return store.context(body)

    @app.get("/api/runs")
    def runs(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
        return store.list_runs(limit, offset)

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        return store.get_run(run_id)

    @app.post("/api/backup")
    def backup():
        name = "rfkb-" + uuid.uuid4().hex + ".zip"
        archive = create_backup(store, store.root / "backups" / name)
        return {"name": name, "bytes": archive.stat().st_size}

    @app.get("/api/backups/{name}")
    def download_backup(name: str):
        if not re.fullmatch(r"rfkb-[a-f0-9]{32}\.zip", name):
            raise KBError("Backup not found.", 404)
        archive = store.root / "backups" / name
        if not archive.is_file():
            raise KBError("Backup not found.", 404)
        return FileResponse(archive, media_type="application/zip", filename=name)

    static = Path(__file__).with_name("static")
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="workbench")
    return app
