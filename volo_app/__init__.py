"""volo_app — Volo 데스크톱 UI (PySide6).

엔진(:mod:`volo_engine`)을 호출만 한다. 편집 결과도 ``list[Subtitle]`` 자료형을 유지한다.
UI 스택은 PySide6(근거: docs/ARCHITECTURE.md). 엔진과의 경계는 깨지지 않는다.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
