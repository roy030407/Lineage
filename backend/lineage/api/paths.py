"""Validating that a caller-supplied name stays inside its intended root.

Scanning a string for separators is not sufficient, which is the whole
reason this module exists. On Windows a drive-relative name like
'C:evil.yaml' contains no separator and no '..', yet

    Path('data/lines') / 'C:evil.yaml'

evaluates to 'C:evil.yaml': the drive letter re-anchors the path and the
join is silently discarded. Verified on the development machine against the
builder's save handler, which rejected '/', '\\' and '..' and still let
that through.

The only reliable check is to resolve the candidate and compare its parent
against the resolved root, so this module does both: a cheap name check
that catches the common cases with a clear message, and a resolve-and-
compare backstop for anything platform-specific the name check misses.
"""

from pathlib import Path

_REJECTED_NAMES = frozenset({"", ".", ".."})


def safe_child(root: Path, name: str) -> Path:
    """Return `root / name`, or raise ValueError if `name` is anything
    other than a plain child basename of `root`.

    Raises ValueError rather than returning None or an HTTPException so
    this module stays free of any FastAPI dependency and is testable on its
    own; callers translate to a 400.
    """
    if name in _REJECTED_NAMES:
        raise ValueError("name must be a plain filename, not empty or a directory reference")
    if Path(name).name != name:
        # Catches separators, parent references, absolute paths, UNC paths,
        # and Windows drive-relative names in one comparison: for any of
        # those, pathlib's own basename differs from what was supplied.
        raise ValueError("name must be a plain filename with no path separators or drive prefix")

    candidate = (root / name).resolve()
    if candidate.parent != Path(root).resolve():
        raise ValueError("name must resolve to a direct child of the intended directory")
    return root / name
