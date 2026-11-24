import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from .evaluation import check_parameters
from .retrieval import family_matches, query_variants
from .validation import (CASE_TYPES, RULE_MODES, KBError, digest, encode, payload,
                         publication_content, text, version_number)

CASE_TYPE_SQL = "COALESCE(json_extract(v.body_json, '$.case_type'), c.case_type)"
CLASSIFICATION_JOIN = (" LEFT JOIN legacy_case_classifications c ON c.record_id=v.record_id "
                       "AND c.version=v.version AND c.content_hash=v.content_hash ")
RECORD_FIELDS = f"v.*,r.kind,r.test_only,{CASE_TYPE_SQL} AS indexed_case_type"
RULE_MODE_SQL = ("CASE json_extract(v.body_json, '$.operation') "
                 "WHEN 'manual' THEN 'manual' WHEN 'clearance' THEN 'automatic' END")


def now():
    return datetime.now(timezone.utc).isoformat()


VALIDATION_NOTE = "自动校验通过；未执行人工工程审核。"


class KnowledgeStore:
    def __init__(self, root, test_mode=False):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "library.sqlite3"
        self.artifacts_dir = self.root / "artifacts"
        self.artifacts_dir.mkdir(exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('test_mode',?)",
                       ("1" if test_mode else "0",))

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.create_function("family_matches", 2, family_matches, deterministic=True)
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _row(self, db, rid, version=None):
        rid = text(rid, "Record ID", 80)
        query = ("SELECT " + RECORD_FIELDS + " FROM revisions v JOIN records r ON r.id=v.record_id"
                 + CLASSIFICATION_JOIN)
        if version is None:
            row = db.execute(
                query + "WHERE v.record_id=? AND v.status='published'", (rid,)).fetchone()
        else:
            version_number(version)
            row = db.execute(
                query + "WHERE v.record_id=? AND v.version=?", (rid, version)).fetchone()
        if row is None:
            raise KBError("Record/version is not available.", 404)
        return row

    @staticmethod
    def _record(row):
        result = dict(row)
        result.pop("rowid", None)
        result["body"] = json.loads(result.pop("body_json"))
        result["references"] = json.loads(result.pop("references_json"))
        result["test_only"] = bool(result["test_only"])
        indexed_case_type = result.pop("indexed_case_type", None)
        result["case_type"] = indexed_case_type if result["kind"] == "case" else None
        result["rule_mode"] = {"manual": "manual", "clearance": "automatic"}.get(
            str(result["body"].get("operation"))) if result["kind"] == "rule" else None
        return result

    def get_record(self, rid, version=None):
        with self.connection() as db:
            return self._record(self._row(db, rid, version))

    def classify_legacy_case(self, rid, version, expected_hash, case_type):
        if case_type not in CASE_TYPES:
            raise KBError("Unknown case type.")
        version_number(version)
        with self.connection(write=True) as db:
            row = self._row(db, rid, version)
            if row["kind"] != "case" or row["content_hash"] != expected_hash:
                raise KBError("Case identity or content hash changed.", 409)
            existing = row["indexed_case_type"]
            if existing is not None and existing != case_type:
                raise KBError("The case already has a different classification.", 409)
            if existing is None:
                db.execute("INSERT INTO legacy_case_classifications VALUES (?,?,?,?)",
                           (rid, version, expected_hash, case_type))

    @staticmethod
    def _snapshot(db, rid, version, data, expected_hash, provenance):
        if digest(data) != expected_hash:
            raise KBError("Snapshot payload does not match the recorded hash.", 409)
        db.execute("INSERT INTO revision_snapshots VALUES (?,?,?,?,?,?) "
                   "ON CONFLICT(record_id,version,content_hash) DO NOTHING",
                   (rid, version, expected_hash, encode(data), now(), provenance))

    def import_verified_snapshots(self, snapshots):
        """Add recovery payloads previously matched to a local receipt or database."""
        with self.connection(write=True) as db:
            for rid, version, expected_hash, data, provenance in snapshots:
                version_number(version)
                row = self._row(db, rid, version)
                data = payload(data)
                if row["kind"] != data["kind"] or bool(row["test_only"]) != data["test_only"]:
                    raise KBError("Snapshot record scope changed.", 409)
                self._snapshot(db, rid, version, data, expected_hash, text(provenance, "Provenance", 1000))

    def list_snapshots(self, rid, version):
        version_number(version)
        with self.connection() as db:
            self._row(db, rid, version)
            return [dict(row) for row in db.execute(
                "SELECT content_hash,captured_at,provenance FROM revision_snapshots "
                "WHERE record_id=? AND version=? ORDER BY captured_at,content_hash", (rid, version))]

    def get_snapshot(self, rid, version, content_hash):
        version_number(version)
        if not isinstance(content_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", content_hash):
            raise KBError("An exact SHA-256 content hash is required.")
        with self.connection() as db:
            row = db.execute("SELECT * FROM revision_snapshots WHERE record_id=? AND version=? "
                             "AND content_hash=?", (text(rid, "Record ID", 80), version, content_hash)).fetchone()
        if row is None:
            raise KBError("No exact snapshot is available for this hash.", 404)
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        if digest(result["payload"]) != content_hash:
            raise KBError("Snapshot checksum mismatch.", 409)
        return result

    def versions(self, rid):
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                "SELECT version,status,title,edit_token,updated_at,reviewed_by FROM revisions "
                "WHERE record_id=? ORDER BY version DESC", (rid,))]

    def _write_revision(self, db, rid, version, data, token=1, created=None):
        stamp = now()
        body = data["body"]
        args = (rid, version, "draft", data["title"], data["summary"], data["family"],
                str(body.get("role", "")), str(body.get("variant", "")),
                encode(body), encode(data["references"]), digest(data), token, created or stamp, stamp)
        db.execute(
            "INSERT INTO revisions(record_id,version,status,title,summary,family,role,variant,"
            "body_json,references_json,content_hash,edit_token,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", args)
        rowid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO record_search(rowid,title,summary,body) VALUES (?,?,?,?)",
                   (rowid, data["title"], data["summary"], encode(body)))

    def _audit(self, db, rid, version, action, actor, note, before, after):
        event = db.execute(
            "INSERT INTO audit_events(record_id,version,action,actor,note,from_status,to_status,created_at)"
            " VALUES (?,?,?,?,?,?,?,?)", (rid, version, action, actor, note, before, after, now()))
        if action in {"create", "save", "new_version", "submit", "validate_publish"}:
            row = self._row(db, rid, version)
            self._snapshot(db, rid, version, payload(self._record(row)), row["content_hash"], action)
            db.execute("INSERT INTO audit_snapshots VALUES (?,?,?,?)",
                       (event.lastrowid, rid, version, row["content_hash"]))

    def create_record(self, data, actor, *, publish=False):
        data, actor = payload(data), text(actor, "Actor", 80)
        rid = str(uuid.uuid4())
        with self.connection(write=True) as db:
            if (not data["test_only"]
                    and db.execute("SELECT value FROM metadata WHERE key='test_mode'").fetchone()[0] == "1"):
                raise KBError("A test workspace accepts synthetic test-only records only.")
            db.execute("INSERT INTO records VALUES (?,?,?,?)",
                       (rid, data["kind"], int(data["test_only"]), now()))
            self._write_revision(db, rid, 1, data)
            self._audit(db, rid, 1, "create", actor, "", None, "draft")
            if publish:
                self._change_status(db, self._row(db, rid, 1), "validate_publish", actor, "")
        return self.get_record(rid, 1)

    @staticmethod
    def _editable(row, token):
        if type(token) is not int or token != row["edit_token"]:
            raise KBError("The record changed. Refresh before saving or reviewing.", 409)

    def save_draft(self, rid, version, data, token, actor, *, publish=False):
        data, actor = payload(data), text(actor, "Actor", 80)
        with self.connection(write=True) as db:
            row = self._row(db, rid, version)
            self._editable(row, token)
            if row["status"] != "draft":
                raise KBError("Only draft content may be edited.", 409)
            if row["kind"] != data["kind"] or bool(row["test_only"]) != data["test_only"]:
                raise KBError("Record kind and test-data scope cannot change.", 409)
            # Preserve the pre-edit payload, including drafts created before snapshot tracking.
            self._snapshot(db, rid, version, payload(self._record(row)), row["content_hash"], "before_save")
            if row["kind"] == "case" and row["indexed_case_type"] and "case_type" not in data["body"]:
                data["body"] = {**data["body"], "case_type": row["indexed_case_type"]}
            db.execute(
                "UPDATE revisions SET title=?,summary=?,family=?,role=?,variant=?,body_json=?,"
                "references_json=?,content_hash=?,edit_token=edit_token+1,updated_at=? WHERE rowid=?",
                (data["title"], data["summary"], data["family"], str(data["body"].get("role", "")),
                 str(data["body"].get("variant", "")), encode(data["body"]),
                 encode(data["references"]), digest(data), now(), row["rowid"]))
            db.execute("DELETE FROM record_search WHERE rowid=?", (row["rowid"],))
            db.execute("INSERT INTO record_search(rowid,title,summary,body) VALUES (?,?,?,?)",
                       (row["rowid"], data["title"], data["summary"], encode(data["body"])))
            self._audit(db, rid, version, "save", actor, "", "draft", "draft")
            if publish:
                self._change_status(db, self._row(db, rid, version), "validate_publish", actor, "")
        return self.get_record(rid, version)

    def new_version(self, rid, from_version, actor):
        actor = text(actor, "Actor", 80)
        with self.connection(write=True) as db:
            row = self._row(db, rid, from_version)
            if row["status"] not in {"published", "superseded", "retired"}:
                raise KBError("New revisions must derive from a published historical version.", 409)
            if db.execute("SELECT 1 FROM revisions WHERE record_id=? AND status IN ('draft','pending')",
                          (rid,)).fetchone():
                raise KBError("This record already has a working revision.", 409)
            version = db.execute("SELECT max(version)+1 FROM revisions WHERE record_id=?", (rid,)).fetchone()[0]
            data = payload(self._record(row))
            if row["kind"] == "case" and row["indexed_case_type"] is not None:
                data["body"]["case_type"] = row["indexed_case_type"]
            self._write_revision(db, rid, version, data)
            self._audit(db, rid, version, "new_version", actor, f"Copied version {from_version}", None, "draft")
        return self.get_record(rid, version)

    def transition(self, rid, version, action, token, actor, note):
        actor = text(actor, "Actor/reviewer", 80)
        if not isinstance(note, str) or len(note) > 4000:
            raise KBError("Review note must be text of at most 4000 characters.")
        with self.connection(write=True) as db:
            row = self._row(db, rid, version)
            self._editable(row, token)
            self._change_status(db, row, action, actor, note)
        return self.get_record(rid, version)

    def _change_status(self, db, row, action, actor, note):
        changes = {("draft", "submit"): "pending", ("pending", "return"): "draft",
                   ("draft", "validate_publish"): "published",
                   ("pending", "validate_publish"): "published",
                   ("pending", "publish"): "published", ("published", "retire"): "retired"}
        status = row["status"]
        target = changes.get((status, action))
        if not target:
            raise KBError("This lifecycle transition is not allowed.", 409)
        if action in {"publish", "retire", "return"}:
            text(note, "Review note", 4000)
        if action == "validate_publish":
            note = VALIDATION_NOTE
        if target == "published":
            self._prepare_publication(db, row)
        db.execute("UPDATE revisions SET status=?,edit_token=edit_token+1,updated_at=?,"
                   "reviewed_by=?,review_note=? WHERE rowid=?",
                   (target, now(), actor if action == "publish" else row["reviewed_by"],
                    note if action == "publish" else row["review_note"], row["rowid"]))
        self._audit(db, row["record_id"], row["version"], action, actor, note, status, target)

    def _prepare_publication(self, db, row):
        record = self._record(row)
        for ref in record["references"]:
            dependency = self._row(db, ref["record_id"], ref["version"])
            if dependency["status"] not in {"published", "superseded"}:
                raise KBError("Dependencies must be exact, non-retired published versions.")
            if dependency["test_only"] != row["test_only"]:
                raise KBError("Test and production dependencies cannot be mixed.")
        publication_content(record, self)
        db.execute("UPDATE revisions SET status='superseded',updated_at=?,edit_token=edit_token+1 "
                   "WHERE record_id=? AND status='published'", (now(), row["record_id"]))
        for ref in record["references"]:
            db.execute("INSERT INTO dependencies VALUES (?,?,?,?)",
                       (row["rowid"], ref["record_id"], ref["version"], ref["locator"]))
        if row["kind"] == "interface":
            for spec in record["body"]["constraints"]:
                db.execute("INSERT INTO constraints_index VALUES (?,?,?,?,?,?,?)",
                           (row["rowid"], spec["id"], spec["quantity"], spec["unit"],
                            None if spec.get("lower") is None else str(spec["lower"]),
                            None if spec.get("upper") is None else str(spec["upper"]),
                            str(spec.get("note", ""))))

    def search(self, query="", kind=None, family=None, role=None, variant=None,
               status=None, include_drafts=False, limit=100, offset=0, *, case_type=None, rule_mode=None):
        if not isinstance(query, str) or len(query) > 200:
            raise KBError("Search query must be text of at most 200 characters.")
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise KBError("Invalid search pagination.")
        where, args = [], []
        order = "v.updated_at DESC,v.record_id"
        if not include_drafts:
            where.append("v.status='published'")
        elif status:
            if status not in {"draft", "pending", "published", "superseded", "retired"}:
                raise KBError("Unknown status filter.")
            where.append("v.status=?")
            args.append(status)
        else:
            where.append("v.version=(SELECT max(v2.version) FROM revisions v2 WHERE v2.record_id=v.record_id)")
        for name, value in (("r.kind", kind), ("v.role", role), ("v.variant", variant)):
            if value:
                where.append(name + "=?")
                args.append(value)
        if family:
            where.append("family_matches(v.family, ?)")
            args.append(family)
        for value, allowed, record_kind, projection in (
                (case_type, CASE_TYPES, "case", CASE_TYPE_SQL),
                (rule_mode, RULE_MODES, "rule", RULE_MODE_SQL)):
            if value is not None:
                if value not in allowed:
                    raise KBError("Unknown knowledge classification filter.")
                where.append(f"r.kind=? AND {projection}=?")
                args.extend([record_kind, value])
        if query.strip():
            query = query.strip()
            alternatives = query_variants(query)
            folded = {term.casefold() for term in alternatives}

            def priority(title, part_number):
                part = part_number.strip().casefold() if isinstance(part_number, str) else ""
                if part in folded:
                    return 0
                title = title.casefold()
                return 1 if any(term in title for term in folded) else 2

            order = "search_priority(v.title,json_extract(v.body_json,'$.part_number'))," + order
            long_terms = [term for term in alternatives if len(term) >= 3]
            matches = []
            if long_terms:
                matches.append("v.rowid IN (SELECT rowid FROM record_search WHERE record_search MATCH ?)")
                args.append(" OR ".join('"' + term.replace('"', '""') + '"' for term in long_terms))
            for term in alternatives:
                if len(term) >= 3:
                    continue
                escaped = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                for field in ("title", "summary", "body_json"):
                    matches.append(f"v.{field} LIKE ? ESCAPE '\\'")
                    args.append(escaped)
            where.append("(" + " OR ".join(matches) + ")")
        base = (" FROM revisions v JOIN records r ON r.id=v.record_id " + CLASSIFICATION_JOIN
                + " WHERE " + " AND ".join(where))
        with self.connection() as db:
            if query.strip():
                db.create_function("search_priority", 2, priority, deterministic=True)
            total = db.execute("SELECT count(*)" + base, args).fetchone()[0]
            rows = db.execute("SELECT " + RECORD_FIELDS + base +
                              f" ORDER BY {order} LIMIT ? OFFSET ?",
                              [*args, limit, offset]).fetchall()
            return {"total": total, "items": [self._record(row) for row in rows]}

    def audit(self, rid):
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                "SELECT a.*,s.content_hash FROM audit_events a LEFT JOIN audit_snapshots s "
                "ON s.event_id=a.id WHERE a.record_id=? ORDER BY a.id", (rid,))]

    def add_artifact(self, filename, content):
        if not isinstance(content, bytes) or not content or len(content) > 25 * 1024 * 1024:
            raise KBError("Evidence must contain 1 byte to 25 MB.")
        name = PureWindowsPath(str(filename)).name
        name = Path(name).name
        if name in {"", ".", ".."}:
            raise KBError("Invalid evidence filename.")
        sha = hashlib.sha256(content).hexdigest()
        target = self.artifacts_dir / sha
        try:
            with target.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
                raise KBError("Existing evidence file is corrupt.", 409)
        with self.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?,?)",
                       (sha, sha, name[:250], sha, len(content), now()))
        return self.get_artifact(sha)

    def get_artifact(self, artifact_id):
        artifact_id = text(artifact_id, "Artifact ID", 80)
        with self.connection() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
            if row is None:
                raise KBError("Evidence artifact not found.", 404)
            result = dict(row)
            result["artifact_id"] = result.pop("id")
            return result

    def list_artifacts(self, limit=100, offset=0):
        with self.connection() as db:
            total = db.execute("SELECT count(*) FROM artifacts").fetchone()[0]
            rows = db.execute("SELECT id AS artifact_id,filename,sha256,byte_count,created_at "
                              "FROM artifacts ORDER BY created_at DESC LIMIT ? OFFSET ?",
                              (limit, offset))
            return {"total": total, "items": [dict(row) for row in rows]}

    def artifact_bytes(self, artifact_id):
        info = self.get_artifact(artifact_id)
        file = self.artifacts_dir / info["storage_name"]
        if not file.is_file():
            raise KBError("Evidence artifact file is missing.", 409)
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise KBError("Evidence checksum mismatch.", 409)
        return data

    def stats(self):
        with self.connection() as db:
            result = {name: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
                      for name, table in (("records", "records"), ("revisions", "revisions"),
                                          ("artifacts", "artifacts"), ("runs", "evaluation_runs"))}
            result["statuses"] = {r[0]: r[1] for r in db.execute(
                "SELECT status,count(*) FROM revisions GROUP BY status")}
            result["test_mode"] = db.execute("SELECT value FROM metadata WHERE key='test_mode'").fetchone()[0] == "1"
            result["database"] = str(self.db)
            return result

    def context(self, request):
        if not isinstance(request, dict) or not isinstance(request.get("records"), list):
            raise KBError("Context requires a records list of exact ID/version pairs.")
        if not 1 <= len(request["records"]) <= 30:
            raise KBError("Context requires 1 to 30 roots.")
        records, visited, warnings = [], set(), []

        def visit(ref):
            if not isinstance(ref, dict):
                raise KBError("Invalid context reference.")
            version_number(ref.get("version"))
            key = (text(ref.get("record_id"), "Record ID", 80), ref["version"])
            if key in visited:
                return
            if len(visited) >= 100:
                raise KBError("Context dependency graph exceeds 100 records.")
            visited.add(key)
            record = self.get_record(*key)
            if record["status"] in {"draft", "pending"}:
                raise KBError("Agent context cannot include unpublished knowledge.")
            records.append(record)
            if record["status"] == "retired":
                warnings.append(f"Retired evidence: {key[0]} v{key[1]}")
            for dependency in record["references"]:
                visit(dependency)
        for ref in request["records"]:
            visit(ref)
        identities = [{"record_id": r["record_id"], "version": r["version"],
                       "content_hash": r["content_hash"]} for r in records]
        return {"context_hash": digest(identities), "records": records, "warnings": warnings,
                "test_only": any(r["test_only"] for r in records)}

    def evaluate(self, request, persist=True):
        if not isinstance(request, dict) or not isinstance(request.get("parameters"), dict):
            raise KBError("Evaluation requires structured parameters.")
        if not isinstance(request.get("rules", []), list) or len(request.get("rules", [])) > 20:
            raise KBError("Evaluation rules must be a list of at most 20 exact references.")
        if not all(isinstance(key, str) for key in request["parameters"]):
            raise KBError("Parameter IDs must be text.")
        refs = [request.get("profile")] + request.get("rules", [])
        context = self.context({"records": refs})
        profile = context["records"][0]
        if profile["kind"] != "interface":
            raise KBError("Evaluation profile must be an interface.")
        rules = []
        for ref in request.get("rules", []):
            rule = self.get_record(ref["record_id"], ref["version"])
            if rule["kind"] != "rule" or rule["body"].get("operation") != "clearance":
                raise KBError("Requested rule is not an executable clearance rule.")
            if rule["test_only"] != profile["test_only"]:
                raise KBError("Test and production evaluation inputs cannot be mixed.")
            if not rule["family"] or rule["family"] != profile["family"]:
                raise KBError("Rule family must explicitly match the interface family.")
            semantic_ids = {d["id"] for d in profile["body"]["constraints"]
                            if d["quantity"] == "length"}
            if not {rule["body"]["hole"], rule["body"]["shaft"]}.issubset(semantic_ids):
                raise KBError("Rule inputs must be known length dimensions of this interface.")
            rules.append(rule)
        result = check_parameters(profile, request["parameters"], rules)
        if context["warnings"]:
            result["evidence_warnings"] = context["warnings"]
            if result["outcome"] == "pass":
                result["outcome"] = "insufficient_data"
        result["context_hash"] = context["context_hash"]
        if persist:
            run_id = str(uuid.uuid4())
            result["run_id"] = run_id
            with self.connection(write=True) as db:
                db.execute("INSERT INTO evaluation_runs VALUES (?,?,?,?,?)",
                           (run_id, encode(request), encode(context), encode(result), now()))
        return result

    def get_run(self, run_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM evaluation_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KBError("Evaluation run not found.", 404)
            return {"run_id": row["id"], "request": json.loads(row["request_json"]),
                    "context": json.loads(row["context_json"]),
                    "result": json.loads(row["result_json"]), "created_at": row["created_at"]}

    def list_runs(self, limit=100, offset=0):
        with self.connection() as db:
            total = db.execute("SELECT count(*) FROM evaluation_runs").fetchone()[0]
            rows = db.execute("SELECT id,result_json,created_at FROM evaluation_runs "
                              "ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
            return {"total": total, "items": [
                {"run_id": row["id"], "outcome": json.loads(row["result_json"])["outcome"],
                 "test_only": json.loads(row["result_json"])["test_only"],
                 "created_at": row["created_at"]} for row in rows]}
