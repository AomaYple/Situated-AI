"""领域注册只连接声明与已有 IR，不执行政策或加载任意插件。"""

from dataclasses import replace

import pytest

from pdx.situated import core_contracts as c
from pdx.situated.domain_registry import DomainManifest, validate


def profile():
    evidence = (c.EvidenceRef("common/ai/test.txt", 1),)
    return c.CapabilityProfile(
        "1.15.0",
        "fixture_build",
        (("common/ai/test.txt", "a" * 64),),
        (),
        (c.CapabilitySpec("read.income", "known", evidence),),
    )


def domains():
    finance = DomainManifest(
        "finance",
        ("finance.facts",),
        (),
        (),
        ("read.income",),
        (),
        (),
        (),
        (),
        10,
        (),
    )
    politics = DomainManifest(
        "politics",
        ("politics.facts",),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        8,
        (),
    )
    return finance, politics


def test_two_independent_domains_register_with_order_invariant_result():
    finance, politics = domains()
    left = validate((finance, politics), profile())
    right = validate((politics, finance), profile())
    assert left == right
    assert tuple(item.id for item in left.manifests) == ("finance", "politics")
    assert DomainManifest.from_mapping(finance.as_dict()) == finance


def test_dag_orders_dependencies_and_reports_complete_cycle_chain():
    finance, politics = domains()
    politics = replace(politics, dependencies=("finance",), consumes=("finance.facts",))
    assert tuple(item.id for item in validate((politics, finance), profile()).manifests) == (
        "finance",
        "politics",
    )
    with pytest.raises(ValueError, match=r"finance.*politics.*finance"):
        validate((replace(finance, dependencies=("politics",)), politics), profile())


@pytest.mark.parametrize(
    "change",
    [
        {"dependencies": ("absent",)},
        {"requires_capabilities": ("unsupported.reader",)},
        {"consumes": ("private.interface",)},
        {"object_budget": 0},
        {"id": "Bad Domain"},
    ],
)
def test_registry_rejects_invalid_dependencies_capabilities_and_ids(change):
    finance, politics = domains()
    with pytest.raises(ValueError):
        validate((replace(finance, **change), politics), profile())


def test_duplicate_ids_interfaces_and_physical_write_points_fail():
    finance, politics = domains()
    with pytest.raises(ValueError):
        validate((finance, finance), profile())
    with pytest.raises(ValueError):
        validate((finance, replace(politics, provides=finance.provides)), profile())
    write = c.WriteOwnership("common/ai/test.txt", "strategy", ("score",), "kernel")
    with pytest.raises(ValueError):
        validate((replace(finance, writes=(write,)), replace(politics, writes=(write,))), profile())


def test_mapping_rejects_free_script_unknown_fields_and_schema_drift():
    data = domains()[0].as_dict()
    for changes in ({"script": "add = 100"}, {"schema_version": 8}):
        with pytest.raises(ValueError):
            DomainManifest.from_mapping(data | changes)


def test_configuration_rejects_values_and_missing_enabled_dependencies():
    option = c.ConfigurationOption(
        "finance.enabled",
        "boolean",
        False,
        (),
        None,
        None,
        ("finance",),
        ("read.income",),
        (),
        False,
    )
    config = c.ConfigurationSpec((option,), ())
    assert config.resolve({}, modules=frozenset(), capabilities=frozenset()) == (
        ("finance.enabled", False),
    )
    assert config.resolve(
        {"finance.enabled": True},
        modules=frozenset({"finance"}),
        capabilities=frozenset({"read.income"}),
    ) == (("finance.enabled", True),)
    for values in ({"finance.enabled": 1}, {"finance.enabled": "yes"}, {"absent": True}):
        with pytest.raises(ValueError):
            config.resolve(values, modules=frozenset({"finance"}), capabilities=frozenset())
    with pytest.raises(ValueError):
        config.resolve({"finance.enabled": True}, modules=frozenset(), capabilities=frozenset())


def test_configuration_conflicts_and_option_dependencies_are_explicit():
    alpha = c.ConfigurationOption("alpha", "boolean", False, (), None, None, (), (), (), False)
    beta = replace(alpha, id="beta", requires_options=("alpha",))
    config = c.ConfigurationSpec((alpha, beta), (("alpha", "beta"),))
    with pytest.raises(ValueError):
        config.resolve({"beta": True}, modules=frozenset(), capabilities=frozenset())
    with pytest.raises(ValueError):
        config.resolve({"alpha": True, "beta": True}, modules=frozenset(), capabilities=frozenset())


def test_profile_content_hashes_and_known_capabilities_require_evidence():
    with pytest.raises(ValueError):
        replace(profile(), input_hashes=(("common/ai/test.txt", "invalid"),))
    with pytest.raises(ValueError):
        c.CapabilitySpec("read.income", "known", ())
