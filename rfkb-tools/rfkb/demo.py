from .store import KBError, KnowledgeStore


def initialize(root):
    store = KnowledgeStore(root, test_mode=True)
    if not store.stats()["test_mode"] or store.stats()["records"]:
        raise KBError("Demo initialization requires an empty test-mode directory.")
    artifact = store.add_artifact(
        "TEST-ONLY.txt", b"TEST ONLY. Synthetic infrastructure data. Not a connector standard.")

    def publish(data):
        data = {**data, "family": "TEST", "test_only": True}
        record = store.create_record(data, "Demo initializer")
        pending = store.transition(record["record_id"], 1, "submit", record["edit_token"],
                                   "Demo initializer", "Synthetic fixture")
        return store.transition(record["record_id"], 1, "publish", pending["edit_token"],
                                "Demo reviewer", "Synthetic test data, not an engineering review")

    source = publish({
        "kind": "source", "title": "TEST ONLY · 合成证据",
        "summary": "仅用于测试资料、版本和审核流程。",
        "body": {"artifact_id": artifact["artifact_id"], "document_code": "TEST-DOC",
                 "edition": "TEST-1", "issuer": "Synthetic fixture"}})
    reference = {"record_id": source["record_id"], "version": 1, "locator": "合成资料第 1 页"}
    profile = publish({
        "kind": "interface", "title": "TEST ONLY · 合成接口 Alpha",
        "summary": "中文检索测试。数值完全为测试构造，不代表任何连接器。",
        "references": [reference],
        "body": {"role": "pin", "variant": "test-alpha", "grade": "test",
                 "constraints": [
                     {"id": "shaft", "quantity": "length", "unit": "mm", "lower": "9", "upper": "10"},
                     {"id": "hole", "quantity": "length", "unit": "mm", "lower": "10.1", "upper": "11"}]}})
    rule = publish({
        "kind": "rule", "title": "TEST ONLY · 合成间隙检查",
        "references": [reference], "body": {
            "operation": "clearance", "hole": "hole", "shaft": "shaft",
            "unit": "mm", "lower": "0.1", "upper": "1.5"}})
    return {"source": source["record_id"], "interface": profile["record_id"],
            "rule": rule["record_id"], "data": str(store.root), "test_only": True}
