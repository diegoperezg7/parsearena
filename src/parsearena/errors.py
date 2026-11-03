"""Errors that are shown to the user as a short message, never as a traceback."""

from __future__ import annotations


class UserError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class BudgetExceeded(UserError):
    pass
