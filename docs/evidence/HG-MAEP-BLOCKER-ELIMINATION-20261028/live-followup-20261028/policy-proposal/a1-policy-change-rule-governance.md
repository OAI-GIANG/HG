# A-1 Decision Record — policy_change_rule_ref

Task: `HG-MAEP-BLOCKER-ELIMINATION-20261028`
Decision selected by owner: A-1a — retain trust root generation 1.

Evidence inspected in the HG candidate:
- `maep/native_authority.py`: `TrustRootRecord` validates the reference as a non-empty string for root integrity; no production source dereferences the value as a rule document.
- `runtime/factory_preflight.py`: reports the resolved file as NOTICE only, explicitly labels A-1 as an owner decision.
- `docs/evidence/HG-MAEP-BLOCKER-ELIMINATION-20261028/pr62-wp3.md`: records A-1a as documentation/label treatment under D2-a, with no root change.
- Current device root is generation 1 and points to `file://~/.config/hg/authority/policy-change-rule.json`; the file is absent in the inspected authority directory.

Implementation interpretation:
- Keep the root unchanged.
- Treat `policy_change_rule_ref` as a historical/governance label, not as a machine-verified external rule, until source code and an owner-approved schema say otherwise.
- Policy changes remain blocked unless the exact policy is approved under D2-a and bound to the active root digest and generation.
- Do not mark the policy-change-reference validation gate as PASS merely because this record exists. Record the actual gate as `DOCUMENTED_NOT_MACHINE_VERIFIED`.
- Do not create a fake `policy-change-rule.json`; do not modify or rotate the active root.
