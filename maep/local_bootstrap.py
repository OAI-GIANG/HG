"""Explicit local bootstrap entrypoint for HG trust-root source.

No root is created by import or construction. Call bootstrap_local_root only
with an explicitly selected isolated directory; production bootstrap remains a
separate, owner-triggered operation and is intentionally not run by this module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from maep.local_authority_store import LocalEvidenceSink, LocalRootStore
from maep.local_owner_authority import LocalOwnerApprovalSource
from maep.native_authority import AuthorityError, TrustRootManager, TrustRootRecord


def bootstrap_local_root(*, data_directory: str | Path,
                         owner_source: LocalOwnerApprovalSource | None = None
                         ) -> TrustRootRecord:
    """Bootstrap one root under an explicit path; intended for isolated/operator use.

    This function is never called on import and does not create policy, activate
    runtime services, initialize Memory, or select a production path implicitly.
    The local source is not a defense against compromise of the same OS account.
    """
    directory = Path(data_directory).expanduser().absolute()
    source = owner_source or LocalOwnerApprovalSource()
    approval: dict[str, Any] = source.load()
    if approval.get("activation_status") != "SOURCE_CREATED_ROOT_NOT_PROVISIONED":
        raise AuthorityError("owner source is not in the initial-root pending state")
    payload = approval.get("root_payload")
    if not isinstance(payload, dict):
        raise AuthorityError("owner source root payload is invalid")
    store = LocalRootStore(directory / "root")
    sink = LocalEvidenceSink(directory / "evidence")
    manager = TrustRootManager(store, source, sink)
    return manager.bootstrap(payload, approval)
