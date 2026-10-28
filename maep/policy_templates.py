"""Strict, versioned resource/scope templates for HG policy v2.

Policy v1 intentionally remains exact-match only. Policy v2 templates are an
explicitly reviewed allowlist, not globbing, regex, prefix matching, or implicit
inheritance. They do not grant anything unless the exact policy digest is owner-
approved and the session grants the same resource/scope template.
"""
from __future__ import annotations

import os
import re
from typing import Any

POLICY_SCHEMA_V2 = "hg.policy.v2"

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SCOPE_SUFFIXES = frozenset({
    ":read", ":write", ":transition", ":evidence:read", ":evidence:write",
    ":knowledge:read", ":knowledge:write", ":knowledge:verify",
    ":candidate:change", ":checkpoint:read", ":checkpoint:write",
    ":resume:record", ":events:read", ":backup:read", ":backup:write",
    ":restore:read", ":restore:create",
})
SCOPE_TEMPLATES = frozenset("memory:task:{task_id}" + suffix for suffix in _SCOPE_SUFFIXES)
RESOURCE_TEMPLATES = frozenset({
    "memory:task/{task_id}",
    "memory:task/{task_id}/candidate",
    "memory:evidence/{evidence_id}",
    "memory:knowledge/{claim_id}",
    "memory:knowledge/verify/{claim_id}",
    "memory:knowledge/task/{task_id}",
    "memory:checkpoint/{task_id}",
    "memory:resume/{task_id}",
    "memory:events/{task_id}",
    "file:{relative_path}",
})
_MEMORY_RESOURCE_TEMPLATES = frozenset(item for item in RESOURCE_TEMPLATES if item.startswith("memory:"))
_SOURCE_KEYS = frozenset({
    "schema_version", "status", "version", "root_generation",
    "approval_evidence_refs", "grant_ttl_seconds", "rules",
})
_OPTIONAL_SOURCE_KEYS = frozenset({"applicability_rules"})
_APP_RULE_KEYS = frozenset({"rule_id", "actions", "resource_prefix", "classification"})
_EFFECTIVE_EXTRA_KEYS = frozenset({"provenance_verified", "policy_digest"})
_RULE_KEYS = frozenset({"action", "resource", "match_mode", "effect", "scope"})


class PolicyTemplateError(ValueError):
    """Policy v2 contains an unknown, malformed or unsafe template contract."""


def safe_identifier(value: Any) -> bool:
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def safe_relative_path(value: Any) -> bool:
    """Accept one canonical relative POSIX path; reject traversal and ambiguity."""
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or value.startswith("/") or value.endswith("/") or "//" in value):
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _has_template_marker(value: str) -> bool:
    return "{" in value or "}" in value


def _split_store_binding(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.startswith("memory:"):
        return None
    marker = " [store:"
    if value.count(marker) != 1 or not value.endswith("]"):
        return None
    base, suffix = value.rsplit(marker, 1)
    store_path = suffix[:-1]
    if (not store_path or not os.path.isabs(store_path) or chr(0) in store_path
            or chr(13) in store_path or chr(10) in store_path or "]" in store_path
            or os.path.normpath(store_path) != store_path):
        return None
    return base, store_path


def validate_resource_template(template: Any) -> None:
    if template == "file:{relative_path}":
        return
    binding = _split_store_binding(template)
    if binding is None or binding[0] not in _MEMORY_RESOURCE_TEMPLATES:
        raise PolicyTemplateError("Memory resource template must bind one exact canonical absolute store path")

def validate_scope_value(scope: Any, *, templates_allowed: bool) -> None:
    if not isinstance(scope, str) or not scope.strip():
        raise PolicyTemplateError("policy scope must be a non-empty string")
    if not _has_template_marker(scope):
        return
    if not templates_allowed or scope not in SCOPE_TEMPLATES:
        raise PolicyTemplateError("unknown policy scope template")


def validate_policy_source_v2(policy: Any, *, expected_root_generation: int | None = None) -> None:
    """Validate the untrusted policy object before approval verification or activation."""
    if (not isinstance(policy, dict) or not _SOURCE_KEYS.issubset(policy)
            or not set(policy).issubset(_SOURCE_KEYS | _OPTIONAL_SOURCE_KEYS)):
        raise PolicyTemplateError("policy v2 fields do not match the strict source contract")
    if policy.get("schema_version") != POLICY_SCHEMA_V2 or policy.get("status") != "ACTIVE":
        raise PolicyTemplateError("policy v2 must use schema hg.policy.v2 and status ACTIVE")
    if not isinstance(policy.get("version"), str) or not policy["version"].strip():
        raise PolicyTemplateError("policy version is missing")
    generation = policy.get("root_generation")
    if (not isinstance(generation, int) or isinstance(generation, bool) or generation < 1
            or (expected_root_generation is not None and generation != expected_root_generation)):
        raise PolicyTemplateError("policy root generation is invalid or mismatched")
    refs = policy.get("approval_evidence_refs")
    if (not isinstance(refs, list) or not refs
            or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
            or len(refs) != len(set(refs))):
        raise PolicyTemplateError("policy approval evidence references must be unique and non-empty")
    ttl = policy.get("grant_ttl_seconds")
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 300:
        raise PolicyTemplateError("policy grant TTL must be in 1..300 seconds")
    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        raise PolicyTemplateError("active policy v2 must contain at least one explicit rule")
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or set(rule) != _RULE_KEYS:
            raise PolicyTemplateError(f"policy rule {index} fields do not match the strict contract")
        if (not isinstance(rule.get("action"), str) or not rule["action"].strip()
                or not isinstance(rule.get("resource"), str) or not rule["resource"].strip()
                or rule.get("effect") not in {"ALLOW", "DENY"}):
            raise PolicyTemplateError(f"policy rule {index} has invalid action/resource/effect")
        mode = rule.get("match_mode")
        scopes = rule.get("scope")
        if (not isinstance(scopes, list) or not scopes
                or any(not isinstance(scope, str) or not scope.strip() for scope in scopes)
                or len(scopes) != len(set(scopes))):
            raise PolicyTemplateError(f"policy rule {index} scope must be unique, explicit and non-empty")
        if mode == "EXACT":
            if _has_template_marker(rule["resource"]):
                raise PolicyTemplateError(f"policy rule {index} exact resource may not contain template markers")
            for scope in scopes:
                validate_scope_value(scope, templates_allowed=False)
        elif mode == "TEMPLATE":
            validate_resource_template(rule["resource"])
            for scope in scopes:
                validate_scope_value(scope, templates_allowed=True)
        else:
            raise PolicyTemplateError(f"policy rule {index} match_mode must be EXACT or TEMPLATE")
    applicability_rules = policy.get("applicability_rules")
    if applicability_rules is not None:
        if not isinstance(applicability_rules, list):
            raise PolicyTemplateError("policy applicability_rules must be a list")
        seen_ids = set()
        for index, rule in enumerate(applicability_rules):
            if not isinstance(rule, dict) or set(rule) != _APP_RULE_KEYS:
                raise PolicyTemplateError(f"applicability rule {index} fields do not match the strict contract")
            rule_id, actions, prefix = rule["rule_id"], rule["actions"], rule["resource_prefix"]
            if not isinstance(rule_id, str) or not rule_id.strip() or rule_id in seen_ids:
                raise PolicyTemplateError("applicability rule id is empty or duplicated")
            seen_ids.add(rule_id)
            if (not isinstance(actions, list) or not actions
                    or any(not isinstance(action, str) or not action.strip() for action in actions)
                    or len(actions) != len(set(actions))):
                raise PolicyTemplateError("applicability rule actions must be unique, non-empty strings")
            if not isinstance(prefix, str) or not prefix.startswith("memory:"):
                raise PolicyTemplateError("applicability rules may only cover memory: resources")
            if rule["classification"] != "NOT_REQUIRED":
                raise PolicyTemplateError("policy applicability rules may only declare NOT_REQUIRED")


def validate_effective_policy_v2(policy: Any, *, expected_root_generation: int | None = None) -> None:
    """Validate a policy after LocalPolicyProvider has verified its digest/provenance."""
    if not isinstance(policy, dict):
        raise PolicyTemplateError("effective policy v2 must be an object")
    source = {key: value for key, value in policy.items()
              if key not in _EFFECTIVE_EXTRA_KEYS}
    validate_policy_source_v2(source, expected_root_generation=expected_root_generation)
    if policy.get("provenance_verified") is not True:
        raise PolicyTemplateError("effective policy provenance is not verified")
    digest = policy.get("policy_digest")
    if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        raise PolicyTemplateError("effective policy digest is invalid")


def _resource_value(template: str, resource: str, task_ref: Any) -> str | None:
    if not isinstance(template, str) or not isinstance(resource, str):
        return None
    if template == "file:{relative_path}":
        if not resource.startswith("file:"):
            return None
        value = resource[len("file:"):]
        return value if safe_relative_path(value) else None

    template_binding = _split_store_binding(template)
    resource_binding = _split_store_binding(resource)
    if template_binding is None or resource_binding is None:
        return None
    template_base, template_store = template_binding
    resource_base, resource_store = resource_binding
    # The store path is a literal in policy/session grants, never a wildcard.
    if template_store != resource_store or template_base not in _MEMORY_RESOURCE_TEMPLATES:
        return None
    if "{task_id}" in template_base:
        if not safe_identifier(task_ref):
            return None
        rendered = template_base.replace("{task_id}", task_ref)
        return task_ref if rendered == resource_base else None
    field = "evidence_id" if "{evidence_id}" in template_base else "claim_id"
    marker = "{" + field + "}"
    if marker not in template_base:
        return None
    prefix, suffix = template_base.split(marker, 1)
    if not resource_base.startswith(prefix) or (suffix and not resource_base.endswith(suffix)):
        return None
    end = len(resource_base) - len(suffix) if suffix else len(resource_base)
    value = resource_base[len(prefix):end]
    if not safe_identifier(value):
        return None
    return value if prefix + value + suffix == resource_base else None


def resource_template_matches(template: Any, resource: Any, task_ref: Any) -> bool:
    """Match a known template without globbing and bind Memory resources to one exact store."""
    if not isinstance(template, str) or not isinstance(resource, str):
        return False
    if template != "file:{relative_path}":
        try:
            validate_resource_template(template)
        except PolicyTemplateError:
            return False
    return _resource_value(template, resource, task_ref) is not None

def resource_grant_matches(grants: Any, resource: Any, task_ref: Any, *, templates_allowed: bool) -> bool:
    if not isinstance(grants, list) or not isinstance(resource, str):
        return False
    for grant in grants:
        if not isinstance(grant, str):
            continue
        if not _has_template_marker(grant):
            if grant == resource:
                return True
        elif templates_allowed and resource_template_matches(grant, resource, task_ref):
            return True
    return False


def expand_scope(scope: Any, task_ref: Any, *, templates_allowed: bool) -> str | None:
    if not isinstance(scope, str) or not scope.strip():
        return None
    if not _has_template_marker(scope):
        return scope
    if not templates_allowed or scope not in SCOPE_TEMPLATES or not safe_identifier(task_ref):
        return None
    return scope.replace("{task_id}", task_ref)


def scope_grants_cover(requested_scopes: Any, grants: Any, task_ref: Any, *, templates_allowed: bool) -> bool:
    if (not isinstance(requested_scopes, list) or not requested_scopes
            or not all(isinstance(scope, str) and scope.strip() for scope in requested_scopes)
            or not isinstance(grants, list)):
        return False
    expanded = {
        value for grant in grants
        if (value := expand_scope(grant, task_ref, templates_allowed=templates_allowed)) is not None
    }
    return set(requested_scopes).issubset(expanded)


def policy_rule_matches_v2(rule: Any, *, action: Any, resource: Any,
                           requested_scopes: Any, task_ref: Any) -> bool:
    if not isinstance(rule, dict) or rule.get("action") != action:
        return False
    mode = rule.get("match_mode")
    if mode == "EXACT":
        resource_match = rule.get("resource") == resource
        if not resource_match or _has_template_marker(rule.get("resource", "")):
            return False
        scopes = rule.get("scope")
        if not isinstance(scopes, list) or any(
            _has_template_marker(scope) for scope in scopes if isinstance(scope, str)
        ):
            return False
        expanded_scopes = scopes
    elif mode == "TEMPLATE":
        resource_match = resource_template_matches(rule.get("resource"), resource, task_ref)
        if not resource_match:
            return False
        scopes = rule.get("scope")
        if not isinstance(scopes, list):
            return False
        expanded_scopes = [
            value for scope in scopes
            if (value := expand_scope(scope, task_ref, templates_allowed=True)) is not None
        ]
    else:
        return False
    if (not isinstance(requested_scopes, list) or not requested_scopes
            or any(not isinstance(scope, str) or not scope.strip() for scope in requested_scopes)):
        return False
    return set(requested_scopes).issubset(set(expanded_scopes))
