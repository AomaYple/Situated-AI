"""Current Victoria 3 build selection and installed identity."""

from pathlib import Path

import pytest

from pdx import version_contracts


def test_1152_is_the_current_build_for_default_and_explicit_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    assert version_contracts.require_current() == "1.15.2"
    assert version_contracts.require_current("1.15.2") == "1.15.2"
    assert version_contracts.contract().default_strategy_sha256 == (
        "7fa4e018a796b1f1c04275e7fbc712ac39a4376e86db311f31079b12a8337760"
    )


@pytest.mark.parametrize("historical", ["1.14.5", "1.15.0", "1.15.1"])
def test_online_selection_refuses_retired_build_before_reading_identity(
    monkeypatch: pytest.MonkeyPatch, historical: str
) -> None:
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, historical)
    with pytest.raises(ValueError, match=r"当前仅维护 1\.15\.2"):
        version_contracts.verify_installation_identity(Path("should-not-be-read"))
