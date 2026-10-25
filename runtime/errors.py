"""Shared runtime error types.

Kept in their own module so ``python -m runtime.service`` (module ``__main__``) and a factory
importing ``runtime.service`` see the same class object.
"""


class RuntimeStartupError(RuntimeError):
    """Safe-to-report startup/configuration failure."""
