from copy import deepcopy
import hashlib
import json

import pytest

from openform_contracts.validation import (
    ContractViolation, schema, validate, validate_data, validate_grading,
    validate_manifest, validate_message,
)
from conftest import EXAMPLES


@pytest.mark.parametrize("name", ["words", "quiz", "lab"])
def test_teaching_examples_have_consistent_declared_data_and_assets(name):
    directory = EXAMPLES / name
    manifest = json.loads((directory / "manifest.json").read_text())
    validate_manifest(manifest)
    validate_data(manifest, json.loads((directory / "progress.json").read_text()), final=False)
    validate_data(manifest, json.loads((directory / "submission.json").read_text()), final=True)
    validate_grading(manifest, json.loads((directory / "private-grading.json").read_text()))
    for asset in manifest["assets"]:
        assert hashlib.sha256((directory / asset["path"]).read_bytes()).hexdigest() == asset["sha256"]
    assert "expected" not in json.dumps(manifest)


def test_progress_is_partial_but_final_is_complete(words):
    partial = {"answers": {"q1": "图书馆"}}
    validate_data(words, partial, final=False)
    with pytest.raises(ContractViolation):
        validate_data(words, partial, final=True)
    for data in ({"answers": {"q1": "任意答案"}}, {"studentId": "other-student"}):
        with pytest.raises(ContractViolation):
            validate_data(words, data, final=False)


def test_experiment_rejects_invalid_measurements():
    manifest = json.loads((EXAMPLES / "lab" / "manifest.json").read_text())
    for measurement in ({"temperature": -1}, {"seconds": 10001}, {"temperature": "热"}):
        with pytest.raises(ContractViolation):
            validate_data(manifest, {"observations": [measurement]}, final=False)
    validate_grading(manifest, [])


@pytest.mark.parametrize("change", [
    {"entry": "missing.html"}, {"protocolVersion": "openform.activity/2"},
    {"privateGrading": [{"expected": "secret"}]}, {"title": "  "},
])
def test_manifest_rejects_incompatible_or_private_fields(words, change):
    words.update(change)
    with pytest.raises(ContractViolation):
        validate_manifest(words)


@pytest.mark.parametrize("path", ["../index.html", "/index.html", "a/../index.html", "a//index.html", "a/./index.html", "a\\index.html"])
def test_manifest_rejects_unsafe_package_paths(words, path):
    words["entry"] = path
    words["assets"][0]["path"] = path
    with pytest.raises(ContractViolation):
        validate_manifest(words)


def test_manifest_rejects_duplicate_assets_nonhtml_entry_and_question_errors(words):
    cases = []
    duplicate = deepcopy(words)
    duplicate["assets"].append(deepcopy(duplicate["assets"][0]))
    cases.append(duplicate)
    css = deepcopy(words)
    css["assets"][0]["mediaType"] = "text/css"
    cases.append(css)
    questions = deepcopy(words)
    questions["questions"].append(deepcopy(questions["questions"][0]))
    cases.append(questions)
    undeclared = deepcopy(words)
    undeclared["questions"][0]["dataPath"] = "answers.unknown"
    cases.append(undeclared)
    for case in cases:
        with pytest.raises(ContractViolation):
            validate_manifest(case)


@pytest.mark.parametrize("ref", ["$ref", "$dynamicRef", "$recursiveRef"])
def test_no_schema_reference_can_trigger_network_or_recursion(words, ref):
    words["submissionSchema"]["properties"]["answers"][ref] = "https://example.invalid/schema"
    with pytest.raises(ContractViolation) as error:
        validate_manifest(words)
    assert error.value.details[0]["rule"] == "inlineSchemaOnly"


def test_bad_schema_and_unexplained_history_access_are_rejected(words):
    bad = deepcopy(words)
    bad["submissionSchema"]["required"] = "q1"
    with pytest.raises(ContractViolation):
        validate_manifest(bad)
    words["capabilities"].append("getOwnHistory")
    with pytest.raises(ContractViolation):
        validate_manifest(words)
    words["historyPurpose"] = "本人查看同一空间内获准公开的学习记录。"
    validate_manifest(words)


PARAMS = {
    "ready": {"capabilities": ["ready", "loadProgress", "saveProgress", "submit"]},
    "loadProgress": {}, "getOwnHistory": {}, "getSharedSummary": {},
    "saveProgress": {"idempotencyKey": "operation_12345678", "expectedRevision": 0, "data": {}},
    "submit": {"idempotencyKey": "operation_12345678", "expectedRevision": 0, "data": {}},
    "appendEvents": {"events": [{"eventId": "event1", "kind": "answer.changed", "data": {}}]},
    "requestUpload": {"field": "answers.photo"},
}


def message(method, params):
    return {"protocolVersion": "openform.activity/1", "requestId": "r1", "method": method, "params": params}


@pytest.mark.parametrize("method", PARAMS)
def test_bridge_methods_accept_only_their_declared_parameters(method):
    validate_message(message(method, PARAMS[method]))
    invalid = deepcopy(PARAMS[method])
    invalid["studentId"] = "forged-identity"
    with pytest.raises(ContractViolation):
        validate_message(message(method, invalid))


@pytest.mark.parametrize("value", [float("inf"), float("nan"), b"bytes", {1: "not-a-json-key"}])
def test_nonjson_values_are_rejected_by_all_contract_entrypoints(value):
    with pytest.raises(ContractViolation):
        validate("operation", {"data": {"answer": value}})


def test_message_limits_and_safe_validation_errors():
    with pytest.raises(ContractViolation) as too_big:
        validate_message(message("submit", {"data": {"answer": "a" * 65536}}))
    assert too_big.value.details == [{"path": "", "rule": "maxBytes"}]
    nested = {}
    for _ in range(34):
        nested = {"nested": nested}
    with pytest.raises(ContractViolation) as deep:
        validate_message(message("submit", {"data": nested}))
    assert deep.value.details[0]["rule"] == "maxDepth"
    with pytest.raises(ContractViolation) as unicode:
        validate_message(message("submit", {"data": {"answer": "\ud800"}}))
    assert unicode.value.details[0]["rule"] == "utf8"
    secret = "学生原文和进入凭据不应进入错误"
    with pytest.raises(ContractViolation) as error:
        validate_message(message(secret, {}))
    assert secret not in str(error.value)
    assert secret not in json.dumps(error.value.details, ensure_ascii=False)


def test_schema_copies_and_versioned_handshake():
    changed = schema("handshake")
    changed["properties"]["nonce"]["minLength"] = 0
    assert schema("handshake") != changed
    with pytest.raises(ValueError, match="Unknown contract"):
        schema("../../secret")
    validate("handshake", {"protocolVersion": "openform.activity/1", "phase": "init", "nonce": "a" * 64})
    with pytest.raises(ContractViolation):
        validate("handshake", {"protocolVersion": "openform.activity/1", "phase": "connect", "nonce": "short"})


def test_operation_rejects_invalid_revision_and_accepts_retriable_error():
    operation = {"idempotencyKey": "operation_12345678", "attemptId": "attempt1", "expectedRevision": 0, "data": {}}
    validate("operation", operation)
    operation["expectedRevision"] = -1
    with pytest.raises(ContractViolation):
        validate("operation", operation)
    validate("error", {"code": "RESULT_UNKNOWN", "message": "请查询原请求回执。", "requestId": "r1", "retryable": False, "details": []})


def test_private_grading_is_typed_and_bound_to_unique_questions(words):
    good = {"questionId": "q1", "rule": "equals", "expected": "图书馆", "points": 1}
    validate_grading(words, [good])
    for rules in ([good, good], [{**good, "questionId": "unknown"}], [{**good, "expected": 42}], [{**good, "points": 0}]):
        with pytest.raises(ContractViolation):
            validate_grading(words, rules)


@pytest.mark.parametrize("field", [
    {"type": "string"},
    {"type": "string", "pattern": "(a+)+$"},
    {"type": "string", "anyOf": [{"type": "string"}]},
    {"type": "object", "properties": {}},
    {"type": "array", "items": {"type": "string"}},
    {"type": "string", "maxLength": 16001},
    {"type": "string", "enum": [str(i) for i in range(101)]},
    {"type": "object", "additionalProperties": False, "const": {}},
    {"type": "string", "enum": [{}]},
    {"type": "object", "additionalProperties": False, "properties": {"any": True}},
])
def test_student_schemas_have_a_bounded_grammar(words, field):
    words["progressSchema"]["properties"]["answers"]["properties"]["q1"] = field
    with pytest.raises(ContractViolation):
        validate_manifest(words)


def test_receipt_is_a_server_persistence_claim():
    validate("receipt", {"receiptId": "rc1", "attemptId": "a1", "revision": 1, "state": "submitted", "receivedAt": "2026-10-05T08:00:00Z"})
    with pytest.raises(ContractViolation):
        validate("receipt", {"state": "submitted"})


def test_long_field_paths_still_produce_valid_error_envelopes(words):
    field_name = "long" * 80
    words["progressSchema"]["properties"][field_name] = {"type": "number"}
    validate_manifest(words)
    with pytest.raises(ContractViolation) as error:
        validate_data(words, {field_name: "synthetic invalid value"}, final=False)
    validate("error", {"code": error.value.code, "message": str(error.value), "requestId": "r1", "retryable": False, "details": error.value.details})


def test_bounded_constant_string_and_deep_schema(words):
    cursor = {"type": "string", "const": "fixed"}
    words["progressSchema"]["properties"]["answers"]["properties"]["q1"] = cursor
    validate_manifest(words)
    for _ in range(9):
        cursor = {"type": "object", "properties": {"nested": cursor}, "additionalProperties": False}
    words["progressSchema"]["properties"]["extra"] = cursor
    with pytest.raises(ContractViolation):
        validate_manifest(words)
