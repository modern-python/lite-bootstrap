import ast
import pathlib
import sys

import lite_bootstrap


ALLOWED_NON_STDLIB_ROOTS = frozenset({"lite_bootstrap", "typing_extensions"})
PACKAGE_ROOT = pathlib.Path(lite_bootstrap.__file__).parent


def _unguarded_third_party_imports(path: pathlib.Path) -> set[str]:
    # Only tree.body — statements nested in `if import_checker.is_X_installed:` or
    # `if typing.TYPE_CHECKING:` are deeper and are exactly what this invariant permits.
    roots: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots.add((node.module or "").split(".")[0])
    return {root for root in roots if root not in sys.stdlib_module_names and root not in ALLOWED_NON_STDLIB_ROOTS}


def test_importing_lite_bootstrap_needs_only_the_stdlib_and_typing_extensions() -> None:
    """INVARIANT: no module imports a third-party package at unguarded module scope.

    Every optional dependency is one an install may legitimately lack, so an import of it that is
    not inside an `if import_checker.is_X_installed:` or `if typing.TYPE_CHECKING:` block turns a
    missing extra into a crash at `import lite_bootstrap` — before the user reaches the config that
    would have told the bootstrapper to skip that instrument. This is what breaks it, and it has
    broken four times: `orjson` as a mandatory core dependency; `opentelemetry.sdk` imported under
    the api-only flag, so `lite-bootstrap[fastmcp]` (which pulls the api transitively) could not be
    imported; the OTLP exporters imported the same way; and `typing_extensions` used but undeclared,
    so a bare install of 1.3.0 could not be imported at all.

    The rule is also what makes the free-threaded story work: nothing native is reachable from a
    bare import, so core installs and imports on any interpreter and each unavailable extra degrades
    to a skipped instrument rather than an ImportError. Adding a genuinely mandatory dependency is
    allowed — declare it in `[project.dependencies]` and add it here; ADR-0007 records why
    `typing-extensions` is the only one.
    """
    offenders = {
        str(path.relative_to(PACKAGE_ROOT)): third_party
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if (third_party := _unguarded_third_party_imports(path))
    }

    assert offenders == {}
