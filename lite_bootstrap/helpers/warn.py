import inspect
import types
import typing
import warnings


_DATACLASS_GENERATED_INIT: typing.Final = "<string>"
_INTERNAL_MODULES: typing.Final = frozenset({__name__.split(".")[0], "dataclasses"})


def _is_internal_frame(frame: types.FrameType) -> bool:
    """Return True while the frame still belongs to lite-bootstrap rather than to its user.

    `dataclasses` is in the set because `replace()` calls the constructor itself. The `__init__` it
    generates reports its file as `<string>`, in the defining class's module rather than this one.
    """
    if frame.f_code.co_name == "__init__" and frame.f_code.co_filename == _DATACLASS_GENERATED_INIT:
        return True
    module_name: str = frame.f_globals.get("__name__", "")
    return module_name.split(".", maxsplit=1)[0] in _INTERNAL_MODULES


def warn_at_caller(message: str, category: type[Warning] = UserWarning) -> None:
    """Warn at the nearest frame outside lite-bootstrap's own machinery.

    Both call paths that reach here have a depth no literal `stacklevel` can name: a config's
    `__post_init__` cascade is as deep as that config's MRO chain plus the `__init__`
    `dataclasses` generates, and an instrument's `bootstrap()` sits one frame deeper when it
    calls `super().bootstrap()` first.
    """
    stacklevel = 1
    frame: types.FrameType | None = inspect.currentframe()
    while frame is not None and _is_internal_frame(frame):
        stacklevel += 1
        frame = frame.f_back
    warnings.warn(message, category=category, stacklevel=stacklevel)
