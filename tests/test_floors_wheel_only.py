import pathlib
import re
import typing


_REPO_ROOT: typing.Final = pathlib.Path(__file__).resolve().parent.parent
_WORKFLOW: typing.Final = ".github/workflows/_checks.yml"
_PYPROJECT: typing.Final = "pyproject.toml"
_PROJECT_NAME: typing.Final = "lite-bootstrap"
_DEPENDENCIES_ARRAY: typing.Final = re.compile(r"^dependencies = \[(.*?)^\]", re.MULTILINE | re.DOTALL)
_OPTIONAL_SECTION: typing.Final = re.compile(
    r"^\[project\.optional-dependencies\]\n(.*?)(?=^\[)", re.MULTILINE | re.DOTALL
)
_REQUIREMENT: typing.Final = re.compile(r'"([A-Za-z0-9][A-Za-z0-9._-]*)[^"]*"')
_ONLY_BINARY: typing.Final = re.compile(r"--only-binary[ =]+(\S+)")
_SEPARATOR: typing.Final = re.compile(r"[-_.]+")


def _canonical(name: str) -> str:
    return _SEPARATOR.sub("-", name).lower()


def _published_dependencies(pyproject: str) -> set[str]:
    arrays = _DEPENDENCIES_ARRAY.findall(pyproject) + _OPTIONAL_SECTION.findall(pyproject)
    named = {_canonical(name) for array in arrays for name in _REQUIREMENT.findall(array)}
    return named - {_canonical(_PROJECT_NAME)}


def _wheel_only(workflow: str) -> set[str]:
    return {_canonical(name) for value in _ONLY_BINARY.findall(workflow) for name in value.split(",")}


def unprotected_dependencies(root: pathlib.Path) -> list[str]:
    workflow = (root / _WORKFLOW).read_text(encoding="utf-8")
    if ":all:" in _wheel_only(workflow):
        return []
    return sorted(_published_dependencies((root / _PYPROJECT).read_text(encoding="utf-8")) - _wheel_only(workflow))


def test_every_published_dependency_is_resolved_wheel_only_at_the_floors() -> None:
    """INVARIANT: the floors leg names every published dependency in `--only-binary`.

    Broken by adding a dependency or an extra without extending the flag. Wheel-only is the
    property the org standard calls non-optional for this job: a floor reachable only by
    compiling an sdist is not a floor a user installing a wheel can reach, and without the
    flag the resolver builds one and reports success. A dependency missing from the list is
    therefore gated by nothing, silently.

    The flag names packages rather than using `--no-build`, because that refuses to build this
    project too and the smoke target imports it. Naming packages is what makes this test
    necessary: `--no-build` needs no list and so cannot drift.
    """
    unprotected = unprotected_dependencies(_REPO_ROOT)

    assert unprotected == [], "not resolved wheel-only at the floors: " + ", ".join(unprotected)


def _tree(root: pathlib.Path, pyproject: str, workflow: str) -> pathlib.Path:
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / _WORKFLOW).write_text(workflow, encoding="utf-8")
    (root / _PYPROJECT).write_text(pyproject, encoding="utf-8")
    return root


def test_a_dependency_missing_from_the_flag_is_reported(tmp_path: pathlib.Path) -> None:
    """The scanner is exercised against a known result, so an empty scan cannot pass as a green one."""
    root = _tree(
        tmp_path,
        'dependencies = [\n    "typing-extensions>=4.6",\n    "structlog>=22.2",\n]\n',
        "run: uv pip install --only-binary typing-extensions .\n",
    )

    assert unprotected_dependencies(root) == ["structlog"]


def test_a_dependency_of_an_extra_is_reported(tmp_path: pathlib.Path) -> None:
    """Most of this repo's floors live in extras, not in the core dependency list."""
    root = _tree(
        tmp_path,
        '[project.optional-dependencies]\nsentry = [\n    "sentry-sdk>=2.1.0",\n]\n\n[build-system]\n',
        "run: uv pip install .\n",
    )

    assert unprotected_dependencies(root) == ["sentry-sdk"]


def test_a_self_referential_extra_is_not_a_dependency(tmp_path: pathlib.Path) -> None:
    """The `*-all` extras pull this project's own extras and resolve to nothing to install."""
    root = _tree(
        tmp_path,
        "[project.optional-dependencies]\nfastapi-all = [\n"
        f'    "{_PROJECT_NAME}[fastapi,logging]",\n]\n\n[build-system]\n',
        "run: uv pip install .\n",
    )

    assert unprotected_dependencies(root) == []


def test_names_are_compared_as_pep_503_canonicalises_them(tmp_path: pathlib.Path) -> None:
    """`pyroscope-io` and `Pyroscope_IO` are one package, and either spelling may be written."""
    root = _tree(
        tmp_path,
        'dependencies = [\n    "Pyroscope_IO>=0.8.1",\n]\n',
        "run: uv pip install --only-binary pyroscope-io .\n",
    )

    assert unprotected_dependencies(root) == []


def test_comma_separated_and_repeated_flags_are_both_read(tmp_path: pathlib.Path) -> None:
    """Uv accepts either spelling, so neither may silently leave a dependency ungated."""
    root = _tree(
        tmp_path,
        'dependencies = [\n    "orjson>=3.9",\n    "structlog>=22.2",\n    "fastapi>=0.100",\n]\n',
        "run: uv pip install --only-binary orjson,structlog --only-binary fastapi .\n",
    )

    assert unprotected_dependencies(root) == []


def test_only_binary_all_covers_every_dependency(tmp_path: pathlib.Path) -> None:
    """`:all:` needs no list, so it cannot drift and the invariant has nothing to enforce."""
    root = _tree(
        tmp_path,
        'dependencies = [\n    "orjson>=3.9",\n]\n',
        "run: uv pip install --only-binary :all: .\n",
    )

    assert unprotected_dependencies(root) == []
