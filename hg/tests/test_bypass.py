"""RT-06 B2/B3: application-level bypass attempts against the HG runtime.

Each test calls a public API that could cause the protected effect (a file write under the
adapter root) without going through authorization, and asserts the effect did not happen.
These are application-level checks; they do not show OS-level isolation.
"""
import unittest

from maep.core import MAEPError
from hg.runtime import build_runtime
from hg.tools.gateway import ActionGateway, AdapterFailure, LocalFileWriteAdapter
from hg.verification.evidence import EventLog
from hg.tests.support import PRINCIPAL, TempDirMixin, grant, make_task, write_step

PARAMS = {"path": "out/hello.txt", "content": "bypass"}


class PermitStealer(LocalFileWriteAdapter):
    """Keeps the permit it was given and tries to use it a second time."""
    name = "stealer.write"
    stolen = None

    def _perform(self, params):
        PermitStealer.stolen = self._last_permit
        return super()._perform(params)

    def execute(self, params, permit=None):
        self._last_permit = permit
        return super().execute(params, permit)


class DirectAdapterCallTests(TempDirMixin):
    def target(self):
        return self.root / "out/hello.txt"

    def test_registered_adapter_refuses_a_call_without_a_permit(self):
        rt = self.build([grant()])
        adapter = next(a for a in rt.gateway._adapters.values() if a.name == "fs.write")
        with self.assertRaises(AdapterFailure):
            adapter.execute(PARAMS)
        self.assertFalse(self.target().exists())

    def test_unregistered_adapter_refuses_every_call(self):
        with self.assertRaises(AdapterFailure):
            LocalFileWriteAdapter(self.root).execute(PARAMS)
        self.assertFalse(self.target().exists())

    def test_forged_permit_refused(self):
        rt = self.build([grant()])
        adapter = next(a for a in rt.gateway._adapters.values() if a.name == "fs.write")

        class FakePermit:
            resource = "file:out/hello.txt"
        with self.assertRaises(AdapterFailure):
            adapter.execute(PARAMS, FakePermit())
        self.assertFalse(self.target().exists())

    def test_permit_is_single_use_and_bound_to_its_resource(self):
        rt = self.build([grant()], extra_adapters=[PermitStealer(self.root)])
        rt.orch.execute_task(make_task(), [write_step(tool="stealer.write")])
        stealer = next(a for a in rt.gateway._adapters.values() if a.name == "stealer.write")
        self.target().unlink()
        with self.assertRaises(AdapterFailure):              # replay of a used permit
            stealer.execute(PARAMS, PermitStealer.stolen)
        with self.assertRaises(AdapterFailure):              # same permit, other resource
            stealer.execute({"path": "out/other.txt", "content": "x"}, PermitStealer.stolen)
        self.assertFalse(self.target().exists())
        self.assertFalse((self.root / "out/other.txt").exists())

    def test_unused_permit_for_another_resource_refused(self):
        # Isolates the resource binding from the single-use check. Minting a permit needs the
        # gateway's private key and mint path, i.e. in-process code reaching private state.
        rt = self.build([grant()])
        adapter = next(a for a in rt.gateway._adapters.values() if a.name == "fs.write")
        permit = rt.gateway._permit("file:out/other.txt", "T-1:S-1:99")
        with self.assertRaises(AdapterFailure):
            adapter.execute(PARAMS, permit)
        self.assertFalse(self.target().exists())

    def test_public_adapter_api_cannot_mint_effect_authority(self):
        """The bypass this replaces: adapter.bind(caller_key) + _Permit(caller_key, ...).

        Both half-steps are no longer reachable through public names: registration takes a key
        only ActionGateway mints, and a permit can only be minted through that key.
        """
        adapter = LocalFileWriteAdapter(self.root)
        self.assertFalse(hasattr(adapter, "bind"))
        with self.assertRaises(MAEPError):
            adapter._bind(object())                       # a caller-chosen key is not a key
        with self.assertRaises(AdapterFailure):
            adapter.execute(PARAMS)                       # and an unbound adapter still refuses
        self.assertFalse(self.target().exists())

    def test_adapter_cannot_be_registered_with_a_second_gateway(self):
        rt = self.build([grant()])
        adapter = next(a for a in rt.gateway._adapters.values() if a.name == "fs.write")
        with self.assertRaisesRegex(MAEPError, "another gateway"):
            ActionGateway(rt.store, rt.evaluator, EventLog(self.workdir / "other.jsonl"), [adapter],
                          principal=PRINCIPAL)


class UnanchoredRuntimeTests(TempDirMixin):
    def test_runtime_without_trust_root_refused_by_default(self):
        with self.assertRaisesRegex(MAEPError, "unanchored"):
            build_runtime(self.workdir, [grant()])
        self.assertFalse(self.workdir.exists())             # refused before touching the disk

    def test_fixture_mode_requires_explicit_opt_in_and_is_labelled(self):
        rt = build_runtime(self.workdir, [grant()], allow_fixture_grants=True)
        self.assertEqual(rt.trust, "fixture")

    def test_authority_and_fixture_opt_in_are_exclusive(self):
        with self.assertRaisesRegex(MAEPError, "either"):
            build_runtime(self.workdir, [grant()], allow_fixture_grants=True, authority=object())


    def test_forged_authority_via_the_public_bind_api_is_refused(self):
        """Reproduces the bypass: bind(caller_key) + _Permit(caller_key, ...), no gateway involved."""
        from hg.tools.gateway import _Permit
        adapter = LocalFileWriteAdapter(self.root)
        key = object()
        adapter.bind(key)
        adapter.execute(PARAMS, _Permit(key, "file:out/hello.txt", "T-1:S-1:forged"))
        self.assertFalse(self.target().exists())


if __name__ == "__main__":
    unittest.main()
