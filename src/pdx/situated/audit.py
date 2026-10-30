"""内核审计门面。"""

from __future__ import annotations

from .compiler import audit, load_model


def check() -> list[str]:
    model = load_model()
    return audit(model)
