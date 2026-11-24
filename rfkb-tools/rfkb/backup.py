import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from .validation import KBError

HASH = re.compile(r"^[a-f0-9]{64}$")
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024


def _artifacts(database):
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise KBError("Backup database integrity check failed.")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise KBError("Backup database has broken references.")
        if db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone() != ("1",):
            raise KBError("Unsupported backup schema version.")
        rows = db.execute("SELECT storage_name,sha256,byte_count FROM artifacts").fetchall()
        for name, sha, size in rows:
            if not HASH.fullmatch(name) or name != sha or not 0 < size <= 25 * 1024 * 1024:
                raise KBError("Invalid backup artifact metadata.")
        return rows


def create_backup(store, archive_path):
    target = Path(archive_path).resolve()
    if target.exists():
        raise KBError("Backup destination already exists.", 409)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".backup-") as temp:
        snapshot = Path(temp) / "library.sqlite3"
        with store.connection() as source, closing(sqlite3.connect(snapshot)) as dest:
            source.backup(dest)
        files = {"library.sqlite3": snapshot.read_bytes()}
        for name, sha, size in _artifacts(snapshot):
            data = store.artifact_bytes(sha)
            if len(data) != size:
                raise KBError("Evidence size mismatch.", 409)
            files["artifacts/" + name] = data
        if sum(map(len, files.values())) > MAX_ARCHIVE_BYTES:
            raise KBError("Backup exceeds this release's 1 GB limit.")
        manifest = {"schema_version": 1, "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in files.items()}}
        staged = Path(temp) / "snapshot.zip"
        with ZipFile(staged, "w", ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
            for name, data in files.items():
                archive.writestr(name, data)
        staged.rename(target)
    return target


def restore_backup(archive_path, destination):
    target = Path(destination).resolve()
    if target.exists():
        raise KBError("Restore requires a new, absent destination.", 409)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=target.parent, prefix=".restore-"))
    try:
        with ZipFile(archive_path) as archive:
            members = archive.infolist()
            names = [i.filename for i in members]
            if (len(names) > 10002 or len(names) != len(set(names))
                    or "manifest.json" not in names
                    or sum(i.file_size for i in members) > MAX_ARCHIVE_BYTES):
                raise KBError("Invalid or oversized backup archive.")
            allowed = lambda name: (name in {"manifest.json", "library.sqlite3"}
                                    or re.fullmatch(r"artifacts/[a-f0-9]{64}", name))
            if not all(allowed(name) for name in names):
                raise KBError("Invalid backup member path.")
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > 4 * 1024 * 1024:
                raise KBError("Backup manifest is too large.")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
                raise KBError("Unsupported backup manifest.")
            files = manifest.get("files")
            if (not isinstance(files, dict) or set(files) != set(names) - {"manifest.json"}
                    or "library.sqlite3" not in files):
                raise KBError("Backup manifest does not match archive members.")
            for name, expected in files.items():
                data = archive.read(name)
                if (not isinstance(expected, dict) or expected.get("bytes") != len(data)
                        or expected.get("sha256") != hashlib.sha256(data).hexdigest()):
                    raise KBError("Backup checksum mismatch.")
                file = staging / name
                file.parent.mkdir(exist_ok=True)
                file.write_bytes(data)
            artifacts = _artifacts(staging / "library.sqlite3")
            expected_names = {"library.sqlite3"} | {"artifacts/" + row[0] for row in artifacts}
            if set(files) != expected_names:
                raise KBError("Backup artifact coverage does not match database.")
            for name, sha, size in artifacts:
                data = (staging / "artifacts" / name).read_bytes()
                if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
                    raise KBError("Restored artifact does not match database.")
        (staging / "artifacts").mkdir(exist_ok=True)
        staging.rename(target)
        return target
    except KBError:
        raise
    except (BadZipFile, OSError, ValueError, KeyError, sqlite3.Error, RuntimeError) as exc:
        raise KBError("Backup could not be validated or restored: " + str(exc)) from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging)
