import ast
import os
import pathlib
import re
import typing


_REPO_ROOT: typing.Final = pathlib.Path(__file__).resolve().parent.parent
_ADR_DIR: typing.Final = "docs/adr/"
_CITATION: typing.Final = re.compile(r"docs/adr/\d{4}-[a-z0-9-]+\.md")
_NUMBER_PREFIX: typing.Final = "ADR-"
_NUMBER_CITATION: typing.Final = re.compile(_NUMBER_PREFIX + r"\d{4}")
_UNWALKED_DIR: typing.Final = "node_modules"
# mkdocs build output: a second copy of docs/, whose citations are the originals'.
_GENERATED_DIR: typing.Final = "site"
_SCANNED_SUFFIXES: typing.Final = (".py", ".md", ".toml")


def _scanned_files(root: pathlib.Path) -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if not name.startswith(".") and name not in (_UNWALKED_DIR, _GENERATED_DIR)
        )
        found.extend(pathlib.Path(dirpath, name) for name in sorted(filenames) if name.endswith(_SCANNED_SUFFIXES))
    return found


def _citations(file: pathlib.Path, source: str) -> set[str]:
    texts = [source]
    if file.suffix == ".py":
        # Adjacent literals are joined at parse time, so a path split across them is one string
        # in the AST and two fragments in the raw text.
        texts.extend(
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    return {cited for text in texts for pattern in (_CITATION, _NUMBER_CITATION) for cited in pattern.findall(text)}


def _resolves(root: pathlib.Path, cited: str) -> bool:
    if cited.startswith(_ADR_DIR):
        return (root / cited).is_file()
    return any((root / _ADR_DIR).glob(f"{cited.removeprefix(_NUMBER_PREFIX)}-*.md"))


def unresolved_citations(root: pathlib.Path) -> list[tuple[str, str]]:
    return sorted(
        (file.relative_to(root).as_posix(), cited)
        for file in _scanned_files(root)
        for cited in _citations(file, file.read_text(encoding="utf-8"))
        if not _resolves(root, cited)
    )


def test_every_adr_citation_in_the_repo_resolves() -> None:
    """INVARIANT: every ADR named in this repo resolves, by full path or by bare `ADR-NNNN` number.

    Broken by renaming, renumbering or pruning an ADR without following its citations. The offline
    link gate reads Markdown links only, so a path in a docstring, a comment, a guard message or a
    `pyproject.toml` dependency rationale is otherwise checked by nothing, and neither is the bare
    number form, which is how most of them are written. A user who trips a guard is handed a link
    to follow.

    The number form is checked for existence only: a citation renumbered onto a *different* live
    ADR still resolves, and nothing here can know it now names the wrong decision.
    """
    unresolved = unresolved_citations(_REPO_ROOT)

    assert unresolved == [], "\n".join(f"{file} cites {cited}" for file, cited in unresolved)


def test_a_citation_of_a_missing_adr_is_reported_with_its_citing_file(tmp_path: pathlib.Path) -> None:
    """The scanner is exercised against a known result, so an empty scan cannot pass as a green one."""
    (tmp_path / _ADR_DIR).mkdir(parents=True)
    (tmp_path / _ADR_DIR / "0001-kept.md").write_text("# kept\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        f'"""Explained in {_ADR_DIR}0001-kept.md and {_ADR_DIR}9999-missing.md."""\n',
        encoding="utf-8",
    )

    assert unresolved_citations(tmp_path) == [("pkg/mod.py", f"{_ADR_DIR}9999-missing.md")]


def test_a_citation_split_across_adjacent_string_literals_is_found(tmp_path: pathlib.Path) -> None:
    """Python joins adjacent literals at parse time, which is what the `nack` guard message relies on."""
    (tmp_path / "guard.py").write_text(
        f'MESSAGE = (\n    "See https://example.invalid/blob/main/{_ADR_DIR}"\n    "0003-split.md."\n)\n',
        encoding="utf-8",
    )

    assert unresolved_citations(tmp_path) == [("guard.py", f"{_ADR_DIR}0003-split.md")]


def test_a_citation_inside_a_hash_comment_is_found(tmp_path: pathlib.Path) -> None:
    """Comments never reach the AST, so the raw text is scanned as well."""
    (tmp_path / "graph.py").write_text(f"# The rule is one-way, see {_ADR_DIR}0009-comment.md\n", encoding="utf-8")

    assert unresolved_citations(tmp_path) == [("graph.py", f"{_ADR_DIR}0009-comment.md")]


def test_a_bare_adr_number_naming_no_file_is_reported(tmp_path: pathlib.Path) -> None:
    """A renumber leaves `ADR-NNNN` prose behind; only the path form was ever checked."""
    (tmp_path / _ADR_DIR).mkdir(parents=True)
    (tmp_path / _ADR_DIR / "0001-kept.md").write_text("# kept\n", encoding="utf-8")
    (tmp_path / "smoke.py").write_text(
        f"# the constraint {_NUMBER_PREFIX}0001 records, unlike {_NUMBER_PREFIX}9999\n", encoding="utf-8"
    )

    assert unresolved_citations(tmp_path) == [("smoke.py", f"{_NUMBER_PREFIX}9999")]


def test_a_citation_outside_python_is_found(tmp_path: pathlib.Path) -> None:
    """`pyproject.toml` explains dependency floors by citing ADRs, and Markdown cites them in prose."""
    (tmp_path / _ADR_DIR).mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(f"# see {_ADR_DIR}0002-floor.md\ndeps = []\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(f"Read {_NUMBER_PREFIX}0004 before editing.\n", encoding="utf-8")

    assert unresolved_citations(tmp_path) == [
        ("AGENTS.md", f"{_NUMBER_PREFIX}0004"),
        ("pyproject.toml", f"{_ADR_DIR}0002-floor.md"),
    ]


def test_a_tree_with_no_citations_and_no_adr_directory_reports_nothing(tmp_path: pathlib.Path) -> None:
    (tmp_path / "plain.py").write_text("X = 1\n", encoding="utf-8")

    assert unresolved_citations(tmp_path) == []


def test_files_under_dot_directories_are_not_scanned(tmp_path: pathlib.Path) -> None:
    """A virtualenv or a cache is not this repo's citations."""
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "vendored.py").write_text(f"# {_ADR_DIR}0001-elsewhere.md\n", encoding="utf-8")
    (tmp_path / _UNWALKED_DIR).mkdir()
    (tmp_path / _UNWALKED_DIR / "dep.py").write_text(f"# {_ADR_DIR}0002-elsewhere.md\n", encoding="utf-8")

    assert unresolved_citations(tmp_path) == []
