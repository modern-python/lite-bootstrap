import re
import typing


VALID_PATH_PATTERN: typing.Final = re.compile(r"^(/[a-zA-Z0-9_-]+)+/?$")


def is_valid_path(maybe_path: str) -> bool:
    return bool(re.fullmatch(VALID_PATH_PATTERN, maybe_path))
