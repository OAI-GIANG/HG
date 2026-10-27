"""Dependency-free validator for the JSON Schema subset the MAEP contracts use.

`maep/spec/SCHEMA_VALIDATION_REPORT_V1.md` records that all six contracts were checked once with
`jsonschema==4.17.3`, installed temporarily for that run. That check is not reproducible in CI
because the validator is deliberately not a project dependency, so until now the contracts had
JSON parsing tests only — an instance that violated `enum`, `$ref`, `minItems`, `format` or
`additionalProperties: false` would still have passed.

This module validates exactly the subset those six schemas use, and `check_supported()` refuses any
keyword outside it. That is the important property: a schema cannot silently gain a constraint that
nothing checks. It is not a general JSON Schema implementation and must not be described as one
(ADR-006, MAEP-024).

Supported: `$schema`, `$id`, `title`, `description`, `type` (string or list), `enum`, `const`,
`properties`, `required`, `additionalProperties` (false or a schema), `items`, `minItems`,
`minLength`, `format` (`date-time` only), `$defs`, and `$ref` of the form `#/$defs/<name>`.
"""
import datetime
import re

SUPPORTED_KEYWORDS = frozenset({
    "$schema", "$id", "title", "description", "type", "enum", "const", "properties", "required",
    "additionalProperties", "items", "minItems", "minLength", "format", "$defs", "$ref",
})
SUPPORTED_FORMATS = frozenset({"date-time"})
_MAPS_OF_SCHEMAS = frozenset({"properties", "$defs"})
_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")


class SchemaError(Exception):
    """The schema or the validator's use of it is wrong; this is never a data verdict."""


class UnsupportedSchemaKeyword(SchemaError):
    """A schema uses a keyword this validator would otherwise ignore."""


def check_supported(schema, where="schema"):
    """Raise unless every keyword in `schema` is one this module actually enforces."""
    if not isinstance(schema, dict):
        raise SchemaError(f"{where}: a schema must be an object, found {type(schema).__name__}")
    for keyword, value in schema.items():
        if keyword not in SUPPORTED_KEYWORDS:
            raise UnsupportedSchemaKeyword(f"{where}: unsupported keyword {keyword!r}")
        if keyword in _MAPS_OF_SCHEMAS:
            if not isinstance(value, dict):
                raise SchemaError(f"{where}.{keyword}: must be an object of schemas")
            for name, sub in value.items():
                check_supported(sub, f"{where}.{keyword}.{name}")
        elif keyword == "items":
            check_supported(value, f"{where}.items")
        elif keyword == "additionalProperties":
            if isinstance(value, dict):
                check_supported(value, f"{where}.additionalProperties")
            elif not isinstance(value, bool):
                raise SchemaError(f"{where}.additionalProperties: must be false or a schema")
        elif keyword == "format":
            if value not in SUPPORTED_FORMATS:
                raise UnsupportedSchemaKeyword(f"{where}: unsupported format {value!r}")
        elif keyword == "type":
            names = [value] if isinstance(value, str) else list(value)
            for name in names:
                if name not in {"object", "array", "string", "number", "integer", "boolean", "null"}:
                    raise UnsupportedSchemaKeyword(f"{where}: unsupported type {name!r}")


def validate(instance, schema):
    """Return a list of human-readable violations; an empty list means the instance conforms."""
    errors = []
    _validate(instance, schema, schema, "$", errors)
    return errors


def _validate(instance, schema, root, path, errors):
    if "$ref" in schema:
        _validate(instance, _resolve(schema["$ref"], root), root, path, errors)
        return
    if "const" in schema and not _same(instance, schema["const"]):
        errors.append(f"{path}: {instance!r} is not the const {schema['const']!r}")
        return
    if "enum" in schema and not any(_same(instance, allowed) for allowed in schema["enum"]):
        errors.append(f"{path}: {instance!r} is not one of {schema['enum']}")
        return
    if "type" in schema and not _matches_type(instance, schema["type"]):
        errors.append(f"{path}: expected type {schema['type']}, found {type(instance).__name__}")
        return
    if isinstance(instance, dict):
        _validate_object(instance, schema, root, path, errors)
    elif isinstance(instance, list):
        _validate_array(instance, schema, root, path, errors)
    elif isinstance(instance, str):
        _validate_string(instance, schema, path, errors)


def _validate_object(instance, schema, root, path, errors):
    for name in schema.get("required", []):
        if name not in instance:
            errors.append(f"{path}: missing required property {name!r}")
    properties = schema.get("properties", {})
    for name, sub in properties.items():
        if name in instance:
            _validate(instance[name], sub, root, f"{path}.{name}", errors)
    additional = schema.get("additionalProperties")
    if additional is False:
        for name in instance:
            if name not in properties:
                errors.append(f"{path}: unexpected property {name!r}")
    elif isinstance(additional, dict):
        for name, value in instance.items():
            if name not in properties:
                _validate(value, additional, root, f"{path}.{name}", errors)


def _validate_array(instance, schema, root, path, errors):
    if "minItems" in schema and len(instance) < schema["minItems"]:
        errors.append(f"{path}: needs at least {schema['minItems']} item(s), found {len(instance)}")
    items = schema.get("items")
    if isinstance(items, dict):
        for position, value in enumerate(instance):
            _validate(value, items, root, f"{path}[{position}]", errors)


def _validate_string(instance, schema, path, errors):
    if "minLength" in schema and len(instance) < schema["minLength"]:
        errors.append(f"{path}: shorter than minLength {schema['minLength']}")
    if schema.get("format") == "date-time" and not is_date_time(instance):
        errors.append(f"{path}: {instance!r} is not an RFC 3339 date-time")


def _resolve(ref, root):
    prefix = "#/$defs/"
    if not isinstance(ref, str) or not ref.startswith(prefix):
        raise UnsupportedSchemaKeyword(f"unsupported $ref {ref!r}: only {prefix}<name> is supported")
    name = ref[len(prefix):]
    definitions = root.get("$defs", {})
    if name not in definitions:
        raise SchemaError(f"$ref {ref!r} does not resolve in this schema")
    return definitions[name]


def _matches_type(instance, declared):
    names = [declared] if isinstance(declared, str) else list(declared)
    return any(_is_type(instance, name) for name in names)


def _is_type(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise UnsupportedSchemaKeyword(f"unsupported type {name!r}")


def _same(left, right):
    """Type-strict equality: `True == 1` in Python, but not in JSON Schema."""
    return type(left) is type(right) and left == right


def is_date_time(text):
    """RFC 3339 `date-time`, with a real calendar date and a mandatory offset."""
    if not isinstance(text, str) or not _DATE_TIME.match(text):
        return False
    try:
        datetime.datetime.fromisoformat(
            text.replace("Z", "+00:00").replace("z", "+00:00").replace("t", "T"))
    except ValueError:
        return False
    return True
