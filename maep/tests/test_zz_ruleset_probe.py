"""Deliberately failing test: proves CI goes red and the ruleset refuses the merge. Never merge."""
import unittest


class RulesetProbe(unittest.TestCase):
    def test_deliberate_failure(self):
        self.fail("ruleset probe: this PR must not be mergeable")
