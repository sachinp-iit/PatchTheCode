"""Validation adapters for candidate fixes."""

from patchthecode.validation.runner import ValidationRunner
from patchthecode.validation.static import CommandResult, StaticValidator

__all__ = ["CommandResult", "StaticValidator", "ValidationRunner"]