import abc


class BaseInstrument(abc.ABC):
    @abc.abstractmethod
    def bootstrap(self) -> None: ...

    @abc.abstractmethod
    def teardown(self) -> None: ...

    @abc.abstractmethod
    def is_ready(self) -> bool: ...
