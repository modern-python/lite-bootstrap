import typing


BootstrapObjectT = typing.TypeVar("BootstrapObjectT", bound=typing.Any)
ApplicationT = typing.TypeVar("ApplicationT", bound=typing.Any)


class UnsetType:
    """Sentinel type for parameters that distinguish 'not passed' from 'explicitly None'.

    The :data:`UNSET` module-level instance is the canonical sentinel. Use
    ``isinstance(value, UnsetType)`` or ``value is UNSET`` to detect it.
    """

    def __repr__(self) -> str:
        return "UNSET"


UNSET: typing.Final[UnsetType] = UnsetType()
