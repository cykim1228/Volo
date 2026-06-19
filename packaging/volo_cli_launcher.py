"""PyInstaller 진입 스크립트 — CLI(`volo`) 실행파일.

GUI(volo_launcher.py)와 별개로, 콘솔형 CLI .exe 를 만들 때의 진입점.
``volo_cli.__main__`` 은 절대 import만 쓰지만, 패키지 경로를 명확히 하기 위해 런처를 둔다.
"""

import sys

from volo_cli.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
