import hashlib
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

KINDS = {"source", "interface", "selection", "rule", "template", "case"}
CASE_TYPES = ("project_case", "general_method")
RULE_MODES = ("manual", "automatic")
UNITS = {"mm": ("length", Decimal(1)), "in": ("length", Decimal("25.4")),
         "deg": ("angle", Decimal(1)), "1": ("dimensionless", Decimal(1))}


class KBError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def encode(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise KBError("Content must be finite JSON data.") from exc


def digest(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise KBError("A finite decimal number is required.")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise KBError("Invalid decimal number.") from exc
    if not result.is_finite() or abs(result) > Decimal("1e30"):
        raise KBError("A finite, bounded decimal number is required.")
    return result


def decimal_text(value):
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def text(value, label, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise KBError(f"{label} is required and must be at most {maximum} characters.")
    return value.strip()


def version_number(value):
    if type(value) is not int or value < 1:
        raise KBError("An exact positive integer version is required.")
    return value


def validate_requirements(body, refs):
    version = body["requirements_schema_version"]
    if type(version) is not int or version != 1:
        raise KBError("Unsupported requirements schema version.")
    items = body.get("acceptance_requirements")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise KBError("Versioned requirements need 1 to 50 items.")
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise KBError("Each requirement must be an object.")
        ident = text(item.get("id"), "Requirement ID", 80)
        if ident in seen:
            raise KBError("Duplicate requirement ID.")
        seen.add(ident)
        text(item.get("metric"), "Metric", 200)
        category = item.get("category")
        if category not in ("acceptance_limit", "diagnostic_reference",
                            "simulation_criterion", "unconfirmed"):
            raise KBError("Unknown requirement category.")
        if category == "unconfirmed":
            if any(item.get(key) is not None for key in ("operator", "value", "unit")):
                raise KBError("An unconfirmed requirement cannot include a threshold.")
        else:
            if item.get("operator") not in ("<", "≤", "=", "≥", ">"):
                raise KBError("A known requirement needs a comparison operator.")
            number(item.get("value"))
            text(item.get("unit"), "Metric unit", 24)
        scope = item.get("scope")
        if not isinstance(scope, dict):
            raise KBError("A requirement needs an engineering scope.")
        text(scope.get("object"), "Scope object", 200)
        text(scope.get("assembly"), "Assembly or test condition", 1000)
        applicable = scope.get("reference_plane_applicable")
        if applicable is not None and type(applicable) is not bool:
            raise KBError("Reference-plane applicability must be a boolean.")
        if applicable is False and scope.get("reference_plane") is not None:
            raise KBError("An inapplicable reference plane cannot include a value.")
        if scope.get("reference_plane") is not None:
            text(scope["reference_plane"], "Reference plane", 500)
        frequency = scope.get("frequency_GHz")
        if frequency is not None:
            if not isinstance(frequency, dict):
                raise KBError("Frequency scope must be an object.")
            text(frequency.get("wording"), "Frequency wording", 200)
            lo, hi = (None if frequency.get(key) is None else number(frequency[key])
                      for key in ("lower", "upper"))
            if ((lo is None and hi is None) or (lo is not None and lo < 0)
                    or (hi is not None and (hi < 0 or (lo is not None and lo > hi)))):
                raise KBError("Invalid frequency scope.")
            included = frequency.get("upper_inclusive")
            if included is not None and (type(included) is not bool or hi is None):
                raise KBError("Invalid upper frequency endpoint.")
        source = item.get("source")
        if not isinstance(source, dict):
            raise KBError("A requirement needs a pinned source.")
        source_id = text(source.get("record_id"), "Requirement source ID", 80)
        source_version = version_number(source.get("version"))
        text(source.get("locator"), "Requirement evidence locator", 1000)
        if (source_id, source_version) not in refs:
            raise KBError("A requirement source must also be a record reference.")
        verification = item.get("verification")
        if (not isinstance(verification, dict)
                or verification.get("status") not in ("not_verified", "simulation_only", "measured")
                or (category == "unconfirmed" and verification["status"] != "not_verified")):
            raise KBError("Invalid requirement verification status.")
        text(verification.get("summary"), "Requirement verification summary", 1500)


def payload(data):
    if (not isinstance(data, dict) or not isinstance(data.get("kind"), str)
            or data["kind"] not in KINDS):
        raise KBError("Unknown knowledge record kind.")
    if type(data.get("test_only")) is not bool:
        raise KBError("test_only must be an explicit boolean.")
    body = data.get("body", {})
    refs = data.get("references", [])
    if not isinstance(body, dict) or not isinstance(refs, list) or len(refs) > 50:
        raise KBError("body must be an object; references must be a bounded list.")
    seen = set()
    references = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise KBError("Invalid reference.")
        rid = text(ref.get("record_id"), "Referenced record ID", 80)
        ver = version_number(ref.get("version"))
        if (rid, ver) in seen:
            raise KBError("Duplicate dependency version.")
        seen.add((rid, ver))
        references.append({"record_id": rid, "version": ver,
                           "locator": text(ref.get("locator"), "Evidence locator", 1000)})
    if data["kind"] == "case":
        if "case_type" in body and body["case_type"] not in CASE_TYPES:
            raise KBError("Unknown case type.")
        if "requirements_schema_version" in body:
            validate_requirements(body, seen)
    if data["kind"] == "rule" and "operation" in body and body["operation"] not in ("manual", "clearance"):
        raise KBError("Unknown rule operation.")
    result = {
        "kind": data["kind"], "title": text(data.get("title"), "Title"),
        "summary": str(data.get("summary", ""))[:4000],
        "family": str(data.get("family", "")).strip()[:100],
        "test_only": data["test_only"], "body": body, "references": references,
    }
    if len(encode(result).encode("utf-8")) > 1_000_000:
        raise KBError("Knowledge content exceeds 1 MB.")
    return result


def interval(spec):
    unit = spec.get("unit")
    if not isinstance(unit, str) or unit not in UNITS:
        raise KBError("Unsupported unit; supported units: mm, in, deg, 1.")
    lo = None if spec.get("lower") is None else number(spec["lower"])
    hi = None if spec.get("upper") is None else number(spec["upper"])
    if lo is None and hi is None:
        raise KBError("At least one interval limit is required.")
    if lo is not None and hi is not None and lo > hi:
        raise KBError("Interval lower limit exceeds upper limit.")
    return lo, hi


def publication_content(record, store):
    body = record["body"]
    kind = record["kind"]
    if kind == "source":
        for field in ("document_code", "edition", "issuer"):
            text(body.get(field), field)
        if body.get("artifact_id"):
            store.artifact_bytes(body["artifact_id"])
        else:
            try:
                url = urlparse(str(body.get("source_url", "")))
                if url.scheme not in {"http", "https"} or not url.hostname:
                    raise ValueError("Missing HTTP host")
            except ValueError as exc:
                raise KBError("A source requires an uploaded artifact or a valid HTTP(S) source URL.") from exc
    else:
        sources = [r for r in record["references"]
                   if store.get_record(r["record_id"], r["version"])["kind"] == "source"]
        if not sources:
            raise KBError("Publication requires a pinned source and evidence locator.")
    if kind == "interface":
        for field in ("role", "variant", "grade"):
            text(body.get(field), field)
        text(record.get("family"), "Interface family", 100)
        dimensions = body.get("constraints")
        if not isinstance(dimensions, list) or not 1 <= len(dimensions) <= 200:
            raise KBError("An interface needs 1 to 200 reviewed constraints.")
        keys = set()
        for item in dimensions:
            if not isinstance(item, dict):
                raise KBError("Constraint must be an object.")
            key = text(item.get("id"), "Dimension semantic ID", 100)
            if key in keys:
                raise KBError("Duplicate dimension semantic ID.")
            keys.add(key)
            interval(item)
            if item.get("quantity") != UNITS[item["unit"]][0]:
                raise KBError("Constraint quantity and unit disagree.")
            if item.get("condition") or item.get("expression"):
                raise KBError("Conditional/executable constraints are not supported in this release.")
    if kind == "rule":
        if body.get("operation") == "manual":
            text(body.get("review_instructions"), "Manual review instructions", 10000)
            return
        if body.get("operation") != "clearance":
            raise KBError("Select manual review or the clearance operation.")
        text(body.get("hole"), "Hole input semantic ID")
        text(body.get("shaft"), "Shaft input semantic ID")
        interval(body)
        if UNITS[body["unit"]][0] != "length":
            raise KBError("Clearance rules must use length units.")
    if kind in {"selection", "template"}:
        ref = body.get("profile_ref", {})
        if not isinstance(ref, dict):
            raise KBError("An exact profile_ref is required.")
        if not any(r["record_id"] == ref.get("record_id")
                   and r["version"] == ref.get("version") for r in record["references"]):
            raise KBError("profile_ref must also be a pinned reference.")
        profile = store.get_record(ref["record_id"], ref["version"])
        if profile["kind"] != "interface":
            raise KBError("profile_ref must name an interface.")
        if record["family"] != profile["family"]:
            raise KBError("Selection/template family must match its pinned interface.")
        if kind == "selection":
            if not isinstance(body.get("parameters"), dict):
                raise KBError("A selection needs structured parameters.")
            from .evaluation import check_parameters
            result = check_parameters(profile, body["parameters"], [])
            if result["outcome"] != "pass":
                raise KBError("Selection parameters must be complete and within the pinned interface limits.")
        if kind == "template":
            store.artifact_bytes(body.get("artifact_id", ""))
            mapping = body.get("dimension_map")
            if not isinstance(mapping, dict) or not mapping:
                raise KBError("A template needs a semantic-to-native dimension map.")
            if not set(mapping).issubset({d["id"] for d in profile["body"]["constraints"]}):
                raise KBError("Template mapping contains an unknown interface dimension.")
            for native in mapping.values():
                text(native, "Native model dimension name", 300)
    if kind == "case":
        text(body.get("description"), "Case description", 10000)
