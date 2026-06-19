"""volo_cli — Volo 커맨드라인 진입점.

엔진(:mod:`volo_engine`)을 호출만 한다. 자체 자막 로직을 두지 않는다.
CLI 엔트리포인트: ``volo`` → ``volo_cli.__main__:main`` (pyproject.toml [project.scripts]).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
