"""Explicit synthetic fixtures; never connector dimensions or ratings."""


def source_payload(artifact_id):
    return {
        "kind": "source", "title": "TEST ONLY - synthetic evidence",
        "summary": "Synthetic input for infrastructure checks, not a standard.",
        "family": "TEST", "test_only": True, "references": [],
        "body": {"artifact_id": artifact_id, "document_code": "TEST-DOC",
                 "edition": "TEST-1", "issuer": "Infrastructure test fixture"},
    }


def interface_payload(source):
    return {
        "kind": "interface", "title": "TEST ONLY - interface alpha",
        "summary": "中文检索测试；不能用于设计。", "family": "TEST",
        "test_only": True,
        "references": [{"record_id": source["record_id"], "version": source["version"],
                        "locator": "Synthetic page 1, table A"}],
        "body": {
            "role": "pin", "variant": "test-alpha", "grade": "test",
            "constraints": [
                {"id": "shaft", "quantity": "length", "unit": "mm",
                 "lower": "9", "upper": "10", "note": "Synthetic range"},
                {"id": "hole", "quantity": "length", "unit": "mm",
                 "lower": "10.1", "upper": "11"},
            ],
        },
    }


def publish(store, payload, actor="Test reviewer"):
    record = store.create_record(payload, actor)
    pending = store.transition(record["record_id"], record["version"], "submit",
                               record["edit_token"], actor, "Test submission")
    return store.transition(record["record_id"], record["version"], "publish",
                            pending["edit_token"], actor, "Synthetic test review")


def fixture(store):
    evidence = store.add_artifact("synthetic.txt", b"TEST ONLY: no engineering standard.")
    source = publish(store, source_payload(evidence["artifact_id"]))
    interface = publish(store, interface_payload(source))
    return source, interface
