import pytest

from lite_bootstrap.helpers.path import is_valid_path


@pytest.mark.parametrize(
    "path",
    [
        "/metrics",
        "/health/",
        "/api/v1/users",
        "/foo.bar",
        "/foo_bar",
        "/foo-bar",
        "/a",
        "/a/",
    ],
)
def test_is_valid_path_accepts_valid(path: str) -> None:
    assert is_valid_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "",
        "foo",
        "foo/",
        "/foo bar",
        "/foo?bar",
        "/foo#bar",
        "/",
        "//foo",
        "/foo//bar",
    ],
)
def test_is_valid_path_rejects_invalid(path: str) -> None:
    assert is_valid_path(path) is False
