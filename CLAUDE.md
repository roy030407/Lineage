# Lineage — Working Rules

## Before you change anything
1. State a plan and WAIT for my explicit approval before writing code.
   Never edit files in the same turn you first propose the change.
2. Before editing any existing file, read it in full first. Say what
   currently depends on it.
3. If a change would alter behaviour any existing test asserts, STOP and
   ask. Do not update a test to make it pass. Tests are the spec.

## Never break existing code
- Run `pytest -q` before you start and after you finish. Report both.
- If any previously-passing test now fails, revert your change and report.
- New modules must not modify existing module signatures. If you need a
  different signature, propose an additive one and ask.
- Golden files in backend/tests/golden/ are frozen. Regenerating one
  requires my explicit approval, with a diff shown first.

## Non-negotiable invariants
- Nothing hardcodes the number of stations. Everything reads LineSpec.
- A station with no sensor returns risk = UNKNOWN. Never risk = 0 or "safe".
- Act proposals never leave the safety envelope defined in
  backend/lineage/act/envelope.py. That file is append-only.
- Predictions are always emitted with a confidence value attached.

## Style
- Python: type hints everywhere, Pydantic for all boundary objects.
- No new dependency without asking.
- Keep diffs small. One concern per commit.

## After each task
Print: files changed | tests added | tests passing | what I did NOT do