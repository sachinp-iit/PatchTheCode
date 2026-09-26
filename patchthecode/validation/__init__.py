"""Validation adapters for candidate fixes."""

from patchthecode.validation.checkout import CheckoutBuilder
from patchthecode.validation.runner import ValidationRunner
from patchthecode.validation.static import CommandResult, StaticValidator, default_commands

__all__ = [
    "CheckoutBuilder",
    "CommandResult",
    "StaticValidator",
    "ValidationRunner",
    "default_commands",
]