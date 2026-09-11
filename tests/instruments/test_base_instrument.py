import dataclasses

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


def test_base_instrument_defaults() -> None:
    assert BaseInstrument.not_configured_reason == ""
    assert BaseInstrument.missing_dependency_message == ""
    assert BaseInstrument.dependencies_installed() is True
    assert BaseInstrument.is_configured(BaseConfig()) is True


def test_an_instrument_written_against_the_old_attribute_names_still_works() -> None:
    """INVARIANT: a subclass declaring not_ready_message or check_dependencies keeps both behaviours.

    Both names are part of the instrument protocol documented in `docs/introduction/configuration.md`,
    so an out-of-tree instrument may define either. What breaks it is renaming them without the
    forwarding in `BaseInstrument.__init_subclass__`: the bootstrapper would read the inherited empty
    `not_configured_reason` and report no skip reason, and — far worse — it would call the inherited
    `dependencies_installed`, which answers True, and construct an instrument whose optional package
    is absent.
    """

    @dataclasses.dataclass(kw_only=True, slots=True)
    class LegacyInstrument(BaseInstrument[BaseConfig]):
        not_ready_message = "legacy reason"

        @staticmethod
        def check_dependencies() -> bool:
            return False

    assert LegacyInstrument.not_configured_reason == "legacy reason"
    assert LegacyInstrument.dependencies_installed() is False


def test_a_subclass_declaring_both_names_keeps_the_current_one() -> None:
    @dataclasses.dataclass(kw_only=True, slots=True)
    class BothNamesInstrument(BaseInstrument[BaseConfig]):
        not_ready_message = "legacy reason"
        not_configured_reason = "current reason"

    assert BothNamesInstrument.not_configured_reason == "current reason"
