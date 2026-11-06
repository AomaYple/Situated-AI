"""The successor intake must preserve the distinct-current-package premise."""

import pytest
from test_a4_successor import _bind, _case

from tools.ci import a4_classify as classify
from tools.ci import a4_discovery as discovery
from tools.ci.a4_scope import Sources


def test_schema2_intake_rejects_historical_package_even_when_fully_rebound(tmp_path):
    sources, before, after, transition, intake = _case(tmp_path)
    sources = _bind(sources, before, after, transition, intake)
    assert classify.current_intake(sources)["package"]["path"] == "current.zip"

    raw = {**sources.bytes, classify.PACKAGE: sources.read("current.zip")}
    sources = Sources(tmp_path, raw)
    intake["package"] = sources.reference(classify.PACKAGE)
    sources = _bind(sources, before, after, transition, intake)
    sources.verify(intake["package"])
    assert intake["schema"] == 2
    assert "successor" in intake
    with pytest.raises(ValueError, match="distinct from historical PACKAGE"):
        classify.current_intake(sources)

    # This change does not redefine the pre-existing schema1 intake contract.
    historical = {key: value for key, value in intake.items() if key != "successor"}
    historical["schema"] = 1
    sources = Sources(
        tmp_path,
        {**sources.bytes, classify.CURRENT_INTAKE: discovery.encoded(historical)},
    )
    assert classify.current_intake(sources) == historical
