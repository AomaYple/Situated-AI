"""Keep expensive acceptance fixtures together and run full artifact readback early."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from xdist.scheduler import LoadFileScheduling  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Sequence

    from xdist.workermanage import WorkerController  # type: ignore[import-untyped]


_ENGINEERING_RELEASE_READERS = {
    "tests/test_decision_modules.py::test_正式包启用模块与生命周期契约一致",
    "tests/test_decision_modules.py::test_正式候选生成所有脚本和全语言无回退",
    "tests/test_strategic_package.py::test_release_freezes_shared_strategy_and_actual_consumers",
    "tests/test_strategic_package.py::test_release_is_the_public_full_candidate",
}


class AcceptanceScheduling(LoadFileScheduling):
    def _split_scope(self, nodeid: str) -> str:
        module = nodeid.partition("::")[0]
        if nodeid in _ENGINEERING_RELEASE_READERS or module in {
            "tests/test_decisions.py",
            "tests/test_full_information.py",
        }:
            # Keep standard release ZIP and engineering input readers together.
            return "standard_release_package"
        return cast("str", super()._split_scope(nodeid))

    def add_node_collection(self, node: WorkerController, collection: Sequence[str]) -> None:
        super().add_node_collection(node, collection)
        if self.collection is not None and node not in self.registered_collections:
            pytest.exit(
                f"Replacement worker {node.gateway.id} collected different tests",
                returncode=pytest.ExitCode.TESTS_FAILED,
            )

    def _reschedule(self, node: WorkerController) -> None:
        # Another worker can fail while a replacement is still collecting.
        if node in self.registered_collections:
            super()._reschedule(node)

    def schedule(self) -> None:
        if self.collection is None:
            super().schedule()
            return

        # xdist requeues whole workloads when a worker fails, including scopes
        # whose tests already finished. Drop them so every send makes progress.
        for scope, work_unit in list(self.workqueue.items()):
            if all(work_unit.values()):
                del self.workqueue[scope]
        for node in self.nodes:
            if node not in self.registered_collections or node.shutting_down:
                continue
            # The worker reads one item ahead before running its current item.
            while self.workqueue and self._pending_of(self.assigned_work[node]) < 2:
                self._assign_work_unit(node)
        if not self.workqueue:
            for node in self.nodes:
                if not node.shutting_down:
                    node.shutdown()

    def _assign_work_unit(self, node: WorkerController) -> None:
        # Start the JSON readback before workers accumulate analysis data.
        # The two release groups each run real generators for only a few cases,
        # so xdist's item-count order would leave minutes of work at the tail.
        for scope in (
            "tests/test_golden.py",
            "tests/test_profile_configuration.py",
            "tests/test_profile_delivery.py",
        ):
            if scope in self.workqueue:
                self.workqueue.move_to_end(scope, last=False)
                break
        super()._assign_work_unit(node)


@pytest.hookimpl(tryfirst=True)
def pytest_xdist_make_scheduler(config, log):
    if config.getoption("dist") == "loadscope":
        config._sitai_scheduler = "file with release fixture affinity and early artifact readback"
        return AcceptanceScheduling(config, log)
    return None
