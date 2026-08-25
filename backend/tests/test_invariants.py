"""Enforces the project's non-negotiable invariants once real logic exists:
station count is never hardcoded, a station with no sensor returns risk = UNKNOWN,
Act proposals stay within the safety envelope, and predictions always carry a confidence value.
"""
