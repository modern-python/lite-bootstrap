import inspect
import types
import typing
import warnings


_DATACLASS_GENERATED_INIT: typing.Final = "<string>"
_CONSTRUCTION_MODULES: typing.Final = frozenset({__name__.split(".")[0], "dataclasses"})


def _is_internal_frame(frame: types.FrameType) -> bool:
    """Return True while the frame is still part of building a config rather than asking for one.

    `dataclasses` is in the set because `replace()` calls the constructor itself. The `__init__` it
    generates reports its file as `<string>`, in the defining class's module rather than this one.
    """
    if frame.f_code.co_name == "__init__" and frame.f_code.co_filename == _DATACLASS_GENERATED_INIT:
        return True
    module_name: str = frame.f_globals.get("__name__", "")
    return module_name.split(".", maxsplit=1)[0] in _CONSTRUCTION_MODULES


def warn_at_caller(message: str) -> None:
    """Warn at the nearest frame outside the machinery that builds a config.

    Config validation runs inside a `__post_init__` cascade whose depth is the length of that
    config's MRO chain, so no literal `stacklevel` can name the frame that built the config.
    """
    stacklevel = 1
    frame: types.FrameType | None = inspect.currentframe()
    while frame is not None and _is_internal_frame(frame):
        stacklevel += 1
        frame = frame.f_back
    warnings.warn(message, stacklevel=stacklevel)
