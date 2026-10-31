"""D1 阶段收据的输入/输出与状态合同。"""

import pytest

from pdx.situated.receipts import StageReceipt, digest, validate_receipt

pytestmark = pytest.mark.unit


def test_收据要求可复核哈希和输出身份():
    receipt = StageReceipt(
        step_id="D1.01",
        status="verified",
        input_hashes={"source": "a" * 64},
        output_paths=("mod/decisions/action_layers.toml",),
        evidence_ids=("evidence-1",),
        dependencies=("D0",),
    )
    assert validate_receipt(receipt) == ()
    assert digest(receipt.as_dict()) == digest(receipt.as_dict())


def test_收据拒绝非法状态哈希和空身份():
    receipt = StageReceipt(
        step_id="D1.01",
        status="verified",
        input_hashes={"source": "bad"},
        output_paths=(),
        evidence_ids=(),
        dependencies=(),
    )
    problems = validate_receipt(receipt)
    assert {"input_hashes", "output_paths", "evidence_ids", "dependencies"} <= set(problems)


def test_收据失败项只能在非成功状态存在():
    receipt = StageReceipt(
        step_id="D1.01",
        status="verified",
        input_hashes={"source": "a" * 64},
        output_paths=("out.json",),
        evidence_ids=("evidence-1",),
        dependencies=("D0",),
        failures=("unexpected",),
    )
    with pytest.raises(ValueError, match="failures"):
        validate_receipt(receipt, strict=True)


@pytest.mark.parametrize(
    "path",
    [
        "C:/outside.json",
        "C:outside.json",
        "dir/../outside.json",
        "dir\\..\\outside.json",
        "//server/share/file.json",
    ],
)
def test_收据拒绝跨平台绝对路径或路径穿越(path):
    receipt = StageReceipt(
        "D1.01", "verified", {"source": "a" * 64}, (path,), ("witness",), ("D0",)
    )
    assert "output_paths" in validate_receipt(receipt)


@pytest.mark.parametrize(("key", "value"), [("", "a" * 64), ("source", None), ("source", 42)])
def test_非法哈希类型返回明确校验结果(key, value):
    receipt = StageReceipt("D1.01", "verified", {key: value}, ("out.json",), ("witness",), ("D0",))
    assert "input_hashes" in validate_receipt(receipt)
