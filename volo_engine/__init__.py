"""volo_engine — Volo 자막 생성 엔진 (UI 무관 순수 라이브러리).

이 패키지는 영상 → 오디오 추출 → 전사 → 교정 → 세그멘테이션 → (번역) → (스타일) →
내보내기 파이프라인을 제공한다. UI/CLI 는 이 엔진을 **호출만** 한다.

⚠️ 얕은(shallow) __init__ 정책
------------------------------
이 ``__init__`` 은 의도적으로 무거운 의존성을 top-level 에서 import 하지 않는다.
``faster_whisper`` / ``ffmpeg`` / ``imageio_ffmpeg`` 등은 해당 서브모듈
(``transcribe`` / ``audio``)에서만 import 한다. 따라서 다음이 보장된다:

    from volo_engine import models, errors, config        # 항상 가능(stdlib만)
    from volo_engine.segment import segment               # 항상 가능
    from volo_engine.export import export                 # 항상 가능

무거운 의존성이 설치돼 있지 않아도 결정적 모듈(models/segment/export)과 테스트가
import·실행 가능해야 한다. 파이프라인 실행 진입점이 필요하면 명시적으로 가져온다:

    from volo_engine.pipeline import run
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
