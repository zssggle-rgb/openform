"""Validate trusted schemas without echoing user content into errors."""
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json
import math
from pathlib import PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

SCHEMA_NAMES = frozenset({"activity", "operation", "bridge", "error", "handshake", "grading", "receipt"})
MAX_MESSAGE_BYTES = 65536


class ContractViolation(ValueError):
    def __init__(self, details: list[dict[str, str]]):
        self.code = "INVALID_CONTRACT"
        self.details = [{"path": d["path"][:300], "rule": d["rule"][:100]} for d in details[:20]]
        super().__init__("数据不符合活动协议，请检查字段和支持的能力。")


@lru_cache(maxsize=7)
def _validator(name: str) -> Draft202012Validator:
    if name not in SCHEMA_NAMES:
        raise ValueError("Unknown contract schema.")
    schema = json.loads(files("openform_contracts").joinpath("schemas", name + ".json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema(name: str) -> dict[str, Any]:
    """Return an independent schema copy, never a mutable shared validator."""
    return deepcopy(_validator(name).schema)


def validate(name: str, value: Any) -> None:
    """Reject malformed fields and report paths/rules without submitted values."""
    _json_tree(value)
    errors = list(_validator(name).iter_errors(value))
    if errors:
        raise ContractViolation([{"path": "/".join(map(str, error.absolute_path)), "rule": str(error.validator)} for error in errors[:20]])


def _json_tree(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise ContractViolation([{"path": "", "rule": "maxDepth"}])
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ContractViolation([{"path": "", "rule": "stringKeys"}])
        for item in value.values():
            _json_tree(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _json_tree(item, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ContractViolation([{"path": "", "rule": "finiteNumber"}])
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise ContractViolation([{"path": "", "rule": "jsonValue"}])


def validate_message(value: Any) -> None:
    """Only JSON, bounded size/depth and declared methods may reach a host."""
    _json_tree(value)
    try:
        size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except UnicodeEncodeError:
        raise ContractViolation([{"path": "", "rule": "utf8"}]) from None
    if size > MAX_MESSAGE_BYTES:
        raise ContractViolation([{"path": "", "rule": "maxBytes"}])
    validate("bridge", value)


def _field_schema(candidate: dict[str, Any], depth: int = 0) -> None:
    """Bound the supported schema grammar; prohibit regex/branching evaluation."""
    common = {"type", "title", "description", "enum", "const"}
    keywords = {
        "object": {"properties", "required", "additionalProperties"},
        "array": {"items", "minItems", "maxItems"},
        "string": {"minLength", "maxLength"},
        "number": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
        "integer": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
        "boolean": set(), "null": set(),
    }
    kind = candidate.get("type")
    if not isinstance(kind, str) or kind not in keywords or depth > 8 or set(candidate) - common - keywords[kind]:
        raise ContractViolation([{"path": "schema", "rule": "supportedFieldSchema"}])
    if "enum" in candidate and (len(candidate["enum"]) > 100 or any(isinstance(v, (dict, list)) for v in candidate["enum"])):
        raise ContractViolation([{"path": "schema", "rule": "boundedEnum"}])
    if "const" in candidate and isinstance(candidate["const"], (dict, list)):
        raise ContractViolation([{"path": "schema", "rule": "scalarConst"}])
    if kind == "object":
        properties = candidate.get("properties", {})
        if candidate.get("additionalProperties") is not False or len(properties) > 100:
            raise ContractViolation([{"path": "schema", "rule": "closedObject"}])
        for child in properties.values():
            if not isinstance(child, dict):
                raise ContractViolation([{"path": "schema", "rule": "supportedFieldSchema"}])
            _field_schema(child, depth + 1)
    elif kind == "array":
        if not isinstance(candidate.get("items"), dict) or not 0 <= candidate.get("maxItems", 101) <= 100:
            raise ContractViolation([{"path": "schema", "rule": "boundedArray"}])
        _field_schema(candidate["items"], depth + 1)
    elif kind == "string":
        if "maxLength" in candidate:
            bounded = candidate["maxLength"] <= 16000
        elif "enum" in candidate:
            bounded = all(isinstance(v, str) and len(v) <= 16000 for v in candidate["enum"])
        else:
            bounded = isinstance(candidate.get("const"), str) and len(candidate["const"]) <= 16000
        if not bounded:
            raise ContractViolation([{"path": "schema", "rule": "boundedString"}])


def validate_manifest(value: Any) -> None:
    """Check field schemas and references before accepting a draft manifest."""
    _json_tree(value)
    validate("activity", value)
    paths = [asset["path"] for asset in value["assets"]]
    if len(paths) != len(set(paths)) or value["entry"] not in paths:
        raise ContractViolation([{"path": "assets", "rule": "uniqueEntry"}])
    if next(a for a in value["assets"] if a["path"] == value["entry"])["mediaType"] != "text/html":
        raise ContractViolation([{"path": "entry", "rule": "htmlEntry"}])
    for path in paths:
        parts = PurePosixPath(path).parts
        if path.startswith("/") or "\\" in path or any(p in {".", ".."} for p in parts) or str(PurePosixPath(path)) != path:
            raise ContractViolation([{"path": "assets", "rule": "relativePath"}])
    for key in ("progressSchema", "submissionSchema"):
        candidate = value[key]
        # v1 accepts inline JSON Schema. References are explicitly unsupported;
        # no resolver may fetch remote schemas or recurse through cyclic refs.
        pending = [candidate]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if any(k in node for k in ("$ref", "$dynamicRef", "$recursiveRef")):
                    raise ContractViolation([{"path": key, "rule": "inlineSchemaOnly"}])
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        try:
            Draft202012Validator.check_schema(candidate)
        except SchemaError:
            raise ContractViolation([{"path": key, "rule": "validSchema"}]) from None
        _field_schema(candidate)
    ids = [question["id"] for question in value["questions"]]
    if len(ids) != len(set(ids)):
        raise ContractViolation([{"path": "questions", "rule": "uniqueQuestion"}])
    for question in value["questions"]:
        for key in ("progressSchema", "submissionSchema"):
            cursor = value[key]
            for segment in question["dataPath"].split("."):
                cursor = cursor.get("properties", {}).get(segment)
                if not isinstance(cursor, dict):
                    raise ContractViolation([{"path": "questions", "rule": "declaredDataPath"}])
    if "getOwnHistory" in value["capabilities"] and not value.get("historyPurpose", "").strip():
        raise ContractViolation([{"path": "historyPurpose", "rule": "required"}])


def validate_data(manifest: dict[str, Any], value: Any, *, final: bool) -> None:
    """Apply the verified manifest's separate partial-progress/final schemas."""
    _json_tree(value)
    validator = Draft202012Validator(manifest["submissionSchema" if final else "progressSchema"])
    errors = list(validator.iter_errors(value))
    if errors:
        raise ContractViolation([{"path": "/".join(map(str, e.absolute_path)), "rule": str(e.validator)} for e in errors[:20]])


def validate_grading(manifest: dict[str, Any], rules: Any) -> None:
    """Bind server-only scoring rules to questions in an already verified manifest."""
    validate("grading", rules)
    questions = {q["id"]: q for q in manifest["questions"]}
    seen = set()
    for rule in rules:
        if rule["questionId"] not in questions or rule["questionId"] in seen:
            raise ContractViolation([{"path": "grading", "rule": "uniqueDeclaredQuestion"}])
        seen.add(rule["questionId"])
        cursor = manifest["submissionSchema"]
        for segment in questions[rule["questionId"]]["dataPath"].split("."):
            cursor = cursor["properties"][segment]
        if not Draft202012Validator(cursor).is_valid(rule["expected"]):
            raise ContractViolation([{"path": "grading", "rule": "declaredAnswerType"}])
