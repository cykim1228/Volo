"""volo_app 진입점 — 데스크톱 앱 부트스트랩.

실행::

    python -m volo_app

PySide6 가 설치되어 있지 않으면 친절한 안내 후 비0 종료한다(스택트레이스 비노출).
GUI 의존성은 ``[project.optional-dependencies].app`` 으로 분리되어 있다(docs/ARCHITECTURE §2).
"""

from __future__ import annotations

import sys


def main() -> int:
    """앱을 부트스트랩하고 메인 윈도우를 띄운다. 종료 코드를 반환한다."""
    import os

    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication
    except Exception:
        sys.stderr.write(
            "PySide6 가 설치되어 있지 않아 데스크톱 UI를 실행할 수 없습니다.\n"
            "  → 설치: pip install -e .[app]  (또는 pip install PySide6)\n"
        )
        return 1

    from .main_window import STYLE, MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Volo")
    # 일관된 다크 테마: Fusion 베이스 스타일 + QSS(다이얼로그까지 적용) + 기본 폰트.
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    app.setFont(QFont("Malgun Gothic", 10))
    app.setStyleSheet(STYLE)

    window = MainWindow()
    window.show()

    # 스크린샷/데모용: VOLO_DEMO=1 이면 샘플 자막을 미리보기에 채운다(엔진 호출 없음).
    if os.environ.get("VOLO_DEMO"):
        window.load_sample_preview()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
