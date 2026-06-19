"""PyInstaller 진입 스크립트.

``volo_app/__main__.py`` 는 패키지 상대 import(``from .main_window import ...``)를 쓰므로
PyInstaller가 그 파일을 최상위 스크립트로 직접 잡으면 import가 깨진다. 이 런처는 패키지를
정상 경로로 import 해 ``main()`` 을 호출한다.
"""

import sys

from volo_app.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
