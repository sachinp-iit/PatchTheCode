"""Errors shared by the vendor integration facades."""


class UnknownActionError(Exception):
    """Raised when a plan step names an action the facade does not implement.

    The evidence collector catches this and falls back to calling the raw
    connector tool, so a step that is not worth normalizing still contributes
    its payload to the investigation.
    """