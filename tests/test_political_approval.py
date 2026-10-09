"""政治只读态度矩阵的缺失、错误格式与样本配对反例。"""

from __future__ import annotations

import pytest

from pdx import political_approval
from pdx.parser import parse_text

TAGS = ("RUS", "FRA")
IGS = ("ig_landowners", "ig_intelligentsia")
LAWS = ("law_autocracy", "law_census_voting")


def lines():
    return [
        f"SITAI APPROVAL;{tag};{ig};{law};{kind};{value};sample-1"
        for tag in TAGS
        for ig in IGS
        for law in LAWS
        for kind, value in (
            ("EXISTS", "yes"),
            ("NAME", "Observed interest group"),
            ("OBJECT_ID", str(1 + TAGS.index(tag) * len(IGS) + IGS.index(ig))),
            ("OWNER_TAG", tag),
            ("CURRENT", "-3"),
            ("DELTA", "5"),
            ("PREDICTED", "2"),
            ("RADICALIZE", "1" if law == LAWS[0] else "0"),
        )
    ]


def analyze(raw, *, tags=TAGS, igs=IGS, laws=LAWS, anchors=None):
    return political_approval.analyze(
        [political_approval.parse_row(line) for line in raw],
        expected_tags=tags,
        expected_igs=igs,
        expected_laws=laws,
        country_samples=[
            (tag, sample, "Observed country")
            for tag, sample in (
                anchors if anchors is not None else [(tag, "sample-1") for tag in TAGS]
            )
        ],
    )


def test_完整矩阵只验证只读接口而非AI风险否决():
    result = analyze(lines())
    assert result["matrix_complete"]
    assert result["numeric_interface_validated"]
    assert result["radicalize_interface_validated"]
    assert result["receiver_identity_verified"]
    assert result["expected_cells"] == 8
    assert result["observed_cells"] == 8
    assert result["radicalize_values"] == [False, True]
    assert result["ai_veto_proven"] is False
    assert result["quality_improvement_proven"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "missing_row",
        "missing_ig",
        "missing_country",
        "missing_batch",
        "duplicate",
        "cross_sample",
        "unexpected",
        "missing_anchor",
        "duplicate_anchor",
    ],
)
def test_不完整和跨样本不能拼成有效矩阵(fault):
    raw = lines()
    anchors = [(tag, "sample-1") for tag in TAGS]
    if fault == "missing_row":
        raw.pop()
    elif fault == "missing_ig":
        raw = [line for line in raw if IGS[1] not in line]
    elif fault == "missing_country":
        raw = [line for line in raw if ";FRA;" not in line]
    elif fault == "missing_batch":
        anchors.append(("RUS", "sample-2"))
    elif fault == "duplicate":
        raw.append(raw[0])
    elif fault == "cross_sample":
        raw[1] = raw[1].replace("sample-1", "sample-2")
    elif fault == "unexpected":
        raw.append(raw[0].replace("ig_landowners", "ig_devout"))
    elif fault == "missing_anchor":
        anchors.pop()
    else:
        anchors.append(anchors[0])
    result = analyze(raw, anchors=anchors)
    assert not result["matrix_complete"]
    assert not result["numeric_interface_validated"]
    assert not result["radicalize_interface_validated"]
    assert result["issues"]


def test_布尔缺反例不冒充完整验证():
    raw = [line.replace(";RADICALIZE;1;", ";RADICALIZE;0;") for line in lines()]
    result = analyze(raw)
    assert result["matrix_complete"]
    assert result["numeric_interface_validated"]
    assert not result["radicalize_interface_validated"]


@pytest.mark.parametrize("field", ["EXISTS", "CURRENT", "NAME", "OBJECT_ID", "OWNER_TAG"])
def test_同IG同样本的法外状态跨法律必须一致(field):
    raw = lines()
    prefix = "SITAI APPROVAL;RUS;ig_landowners;law_autocracy;"
    if field == "EXISTS":
        raw = [line for line in raw if not line.startswith(prefix)]
        raw.append(prefix + "EXISTS;no;sample-1")
    elif field == "CURRENT":
        raw = [line.replace(prefix + "CURRENT;-3;", prefix + "CURRENT;4;") for line in raw]
    elif field == "NAME":
        raw = [
            line.replace(prefix + "NAME;Observed interest group;", prefix + "NAME;Other group;")
            for line in raw
        ]
    elif field == "OBJECT_ID":
        raw = [line.replace(prefix + "OBJECT_ID;1;", prefix + "OBJECT_ID;99;") for line in raw]
    else:
        raw = [line.replace(prefix + "OWNER_TAG;RUS;", prefix + "OWNER_TAG;FRA;") for line in raw]
    result = analyze(raw)
    assert not result["matrix_complete"]
    assert not result["numeric_interface_validated"]


def test_不存在IG仅允许存在性行且不当数值接口正例():
    raw = [
        f"SITAI APPROVAL;{tag};{ig};{law};EXISTS;no;sample-1"
        for tag in TAGS
        for ig in IGS
        for law in LAWS
    ]
    result = analyze(raw)
    assert result["matrix_complete"]
    assert not result["numeric_interface_validated"]
    assert not result["radicalize_interface_validated"]
    assert not analyze([*raw, lines()[1]])["matrix_complete"]


@pytest.mark.parametrize(
    "value", ["nan", "inf", "1.5", "", "[unresolved]", "2147483648", "−2147483649"]
)
def test_态度整数错误不能当零(value):
    with pytest.raises(ValueError, match="态度"):
        political_approval.parse_row(
            f"SITAI APPROVAL;RUS;ig_landowners;law_autocracy;CURRENT;{value};sample-1"
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("RADICALIZE", "maybe"),
        ("EXISTS", ""),
        ("NAME", "[unresolved]"),
        ("NAME", "\x15title 无政治阵营\x15!"),
        ("OWNER_TAG", ""),
        ("OWNER_TAG", "[unresolved]"),
        ("OBJECT_ID", "0"),
        ("OBJECT_ID", "-1"),
        ("OBJECT_ID", "18446744073709551616"),
        ("UNKNOWN", "1"),
    ],
)
def test_未解析布尔名称和未知字段拒绝(field, value):
    with pytest.raises(ValueError):
        political_approval.parse_row(
            f"SITAI APPROVAL;RUS;ig_landowners;law_autocracy;{field};{value};sample-1"
        )


@pytest.mark.parametrize("sample", ["sample-0", "sample--1", "1836.1.1", "sample-1;trailing"])
def test_样本标识必须严格解析(sample):
    with pytest.raises(ValueError):
        political_approval.parse_row(
            f"SITAI APPROVAL;RUS;ig_landowners;law_autocracy;CURRENT;0;{sample}"
        )


@pytest.mark.parametrize(
    ("igs", "laws"),
    [
        ((), LAWS),
        (IGS, ()),
        (("ig_bad }",), LAWS),
        ((IGS[0], IGS[0]), LAWS),
        (IGS, (LAWS[0], LAWS[0])),
    ],
)
def test_矩阵声明拒绝不成对重复和脚本注入(igs, laws):
    with pytest.raises(ValueError):
        political_approval.validate(igs, laws)


def test_默认关闭且缺预注册不能验证():
    assert political_approval.validate((), ()) == ((), ())
    assert political_approval.readings("RUS", (), (), "sample_var") == ""
    result = analyze(lines(), igs=(), laws=())
    assert not result["matrix_complete"]


def test_观测只读且在原版存在性守卫下读取():
    text = political_approval.readings("RUS", IGS, LAWS, "sample_var")
    assert not parse_text(text).errors
    assert "any_interest_group = { is_interest_group_type = ig_landowners }" in text
    assert "every_interest_group = { limit = { is_interest_group_type = ig_landowners }" in text
    assert "THIS.GetInterestGroup.GetApprovalValue" in text
    assert "THIS.GetInterestGroup.GetID" in text
    assert "THIS.GetInterestGroup.GetCountry.GetTagName" in text
    assert "save_scope_as" not in text
    assert "SCOPE.gsInterestGroup" not in text
    assert "GetInterestGroupOfType" not in text
    assert "GetApprovalValueDeltaFromEnactment(GetLawType('law_census_voting').Self)" in text
    assert "WillRadicalizeIfEnacted(GetLawType('law_autocracy').Self)" in text
    for forbidden in ("set_law", "start_enactment", "add_modifier", "add_treasury", "set_strategy"):
        assert forbidden not in text


def test_默认关闭时保留旧源逐字节一致():
    import hashlib

    from pdx import extension_probe

    text = extension_probe.build(["law_autocracy"], tags=("RUS",))[
        "common/on_actions/zz_sitai_reform_observer.txt"
    ]
    assert (
        hashlib.sha256(text.encode()).hexdigest()
        == "7c4c255af6cbcceb03e2ac807e21e18a89e1f3bac6a064f39723b1ee9b82fd20"
    )


@pytest.mark.parametrize("missing", [False, True])
def test_政治日志单次遍历接入矩阵且整批漏采保持未验证(tmp_path, missing):
    from pdx import extension_probe

    raw = [f"SITAI REFORM;{tag};COUNTRY_NAME;Observed country;sample-1" for tag in TAGS]
    raw += [] if missing else lines()
    (tmp_path / "debug.log").write_bytes(("\n".join(raw) + "\n").encode())
    result = extension_probe.analyze(
        tmp_path, expected_tags=TAGS, expected_approval_igs=IGS, expected_approval_laws=LAWS
    )
    assert result["approval"]["matrix_complete"] is not missing
    assert result["approval"]["numeric_interface_validated"] is not missing


@pytest.mark.parametrize("name", ["", "[unresolved]"])
def test_未解析国家名不能当有效作用域锚点(tmp_path, name):
    from pdx import extension_probe

    raw = [f"SITAI REFORM;{tag};COUNTRY_NAME;{name};sample-1" for tag in TAGS] + lines()
    (tmp_path / "debug.log").write_bytes(("\n".join(raw) + "\n").encode())
    result = extension_probe.analyze(
        tmp_path, expected_tags=TAGS, expected_approval_igs=IGS, expected_approval_laws=LAWS
    )
    assert not result["approval"]["matrix_complete"]
    assert not result["approval"]["numeric_interface_validated"]


def test_旧六字段矩阵缺少receiver身份不能验收():
    raw = [line for line in lines() if ";OBJECT_ID;" not in line and ";OWNER_TAG;" not in line]
    result = analyze(raw)
    assert not result["matrix_complete"]
    assert not result["numeric_interface_validated"]
    assert not result["receiver_identity_verified"]


@pytest.mark.parametrize("fault", ["wrong_country", "same_object"])
def test_可解析的空对象或别国对象不能冒充声明IG(fault):
    raw = lines()
    if fault == "wrong_country":
        raw = [line.replace(";OWNER_TAG;RUS;", ";OWNER_TAG;FRA;") for line in raw]
    else:
        raw = [line.replace(";OBJECT_ID;2;", ";OBJECT_ID;1;") for line in raw]
    result = analyze(raw)
    assert not result["numeric_interface_validated"]
    assert not result["receiver_identity_verified"]
    assert result["issues"]
