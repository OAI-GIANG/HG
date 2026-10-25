"""TERMINAL_STATES: one canonical definition, same name/value as main's maep/core.py."""
import unittest

from maep import core
from maep.core import MAEPError, STATES, TERMINAL_STATES, TRANSITIONS, transition, validate_linked_task


class TerminalStatesTests(unittest.TestCase):
    def test_constant_matches_the_transition_table_and_main(self):
        # main's maep/task_store.py imports this name; its value on main is this set.
        self.assertEqual(TERMINAL_STATES, {"FAILED", "CANCELLED", "CLOSED_VERIFIED"})
        self.assertEqual(TERMINAL_STATES, {state for state, nxt in TRANSITIONS.items() if not nxt})
        self.assertTrue(TERMINAL_STATES <= STATES)

    def test_no_transition_leaves_a_terminal_state(self):
        for state in sorted(TERMINAL_STATES):
            for target in sorted(STATES):
                with self.assertRaisesRegex(MAEPError, "terminal task cannot be reopened"):
                    transition(state, target, guards={"task_valid": True, "authorization_valid": True})

    def test_non_terminal_states_are_not_treated_as_terminal(self):
        self.assertEqual(transition("DRAFT", "READY", guards={"task_valid": True}), "READY")
        for state in sorted(STATES - TERMINAL_STATES):
            self.assertTrue(TRANSITIONS[state], state)

    def test_linked_successor_requires_a_terminal_predecessor(self):
        successor = {"task_id": "T-2", "state": "DRAFT",
                     "inputs": [{"kind": "TASK", "ref_id": "T-1", "description": "predecessor"}]}
        for state in sorted(TERMINAL_STATES):
            self.assertTrue(validate_linked_task({"task_id": "T-1", "state": state}, successor))
        for state in sorted(STATES - TERMINAL_STATES):
            with self.assertRaisesRegex(MAEPError, "predecessor must be terminal"):
                validate_linked_task({"task_id": "T-1", "state": state}, successor)

    def test_consumers_use_the_canonical_constant(self):
        import inspect
        from memory import store
        self.assertIs(store.TERMINAL_STATES, core.TERMINAL_STATES)
        for function in (core.transition, core.validate_linked_task):
            self.assertIn("TERMINAL_STATES", inspect.getsource(function))


if __name__ == "__main__":
    unittest.main()
