# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 스펙 — Volo 데스크톱 앱(.exe) onedir 빌드.

빌드:  pyinstaller packaging/volo.spec   (프로젝트 루트에서 실행)
산출:  dist/Volo/Volo.exe  (+ 동봉 DLL/데이터)

설계 메모
- **onedir** 모드(EXE+COLLECT): LGPL인 Qt(PySide6)/FFmpeg를 별도 파일로 배치해 사용자가
  교체 가능 → LGPL 준수에 유리(THIRD_PARTY_NOTICES.md 참조).
- 모델 가중치는 동봉하지 않는다(수 GB). 최초 실행 시 자동 다운로드.
- faster-whisper/ctranslate2/av/onnxruntime는 동적 로딩이 많아 collect_* 로 보강한다.
- ⚠️ 이 스펙은 빌드 머신에서 검증이 필요한 초안이다. 빌드 후 (1) GUI 실행, (2) 자막 생성
  E2E, (3) assets/presets 로딩(아래 datas), (4) LGPL 동봉 파일을 반드시 점검할 것.
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

# spec 파일 안의 상대경로는 spec 디렉토리 기준으로 해석되므로, SPECPATH(=spec 디렉토리)로
# 절대경로를 만들어 CWD 와 무관하게 동작시킨다. _ROOT = 프로젝트 루트(packaging 의 부모).
_SPECDIR = SPECPATH  # noqa: F821 - PyInstaller 가 주입하는 전역
_ROOT = os.path.dirname(_SPECDIR)

datas = []
binaries = []
hiddenimports = []

# 엔진은 pipeline 에서 지연 import(`from . import audio` 등) → 명시적으로 포함.
hiddenimports += collect_submodules("volo_engine")
hiddenimports += collect_submodules("volo_cli")
hiddenimports += collect_submodules("volo_app")

# 무거운/동적 로딩 의존성 보강.
# imageio_ffmpeg / huggingface_hub 는 audio.py / transcribe.py 에서 **함수 내부 지연 import** 라
# PyInstaller 정적 분석이 못 잡는다 → 반드시 명시 수집해야 ffmpeg 바이너리·다운로드 코드가 동봉된다.
# (누락 시 .exe 는 GUI 만 뜨고 자막 생성 단계에서 "ffmpeg 못 찾음"으로 실패한다.)
for pkg in (
    "faster_whisper",
    "ctranslate2",
    "av",
    "onnxruntime",
    "tokenizers",
    "imageio_ffmpeg",
    "huggingface_hub",
):
    try:
        datas += collect_data_files(pkg)
        hiddenimports += collect_submodules(pkg)
        binaries += collect_dynamic_libs(pkg)
    except Exception as exc:  # 조용한 누락 방지 — 빌드 로그에 노출.
        print(f"[volo.spec] WARN: '{pkg}' collect 실패: {exc}")

# 지연 import 라 정적 분석이 못 잡는 패키지를 명시적으로 hidden import.
hiddenimports += ["imageio_ffmpeg", "huggingface_hub"]
# imageio_ffmpeg 번들 ffmpeg 실행파일(binaries/ffmpeg-*.exe)을 확실히 동봉.
datas += collect_data_files("imageio_ffmpeg", includes=["binaries/*"])

# 스타일 프리셋(런타임에 load_preset 이 읽음). 프로젝트 루트의 assets/ 를 동봉.
#   ⚠️ frozen(번들) 모드에서 style.load_preset 의 경로 해석이 sys._MEIPASS 를 고려하는지
#      확인 필요. 미고려 시 엔진에 frozen 경로 분기를 추가해야 한다.
datas += [(os.path.join(_ROOT, "assets", "presets"), "assets/presets")]


block_cipher = None

a = Analysis(
    [os.path.join(_SPECDIR, "volo_launcher.py")],   # 절대경로(SPECPATH 기준)
    pathex=[_ROOT],           # 루트를 import 경로에 추가(volo_engine/volo_cli/volo_app)
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # faster-whisper는 ctranslate2 백엔드(torch 불필요). onnx/quantization 은 미사용 →
    # 제외해 크기↓ + onnx 미설치 수집 경고 제거(런타임 VAD 는 onnxruntime 추론만 사용).
    excludes=["torch", "tensorflow", "onnx", "onnxruntime.quantization"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,    # onedir: 바이너리는 COLLECT 로 분리
    name="Volo",
    console=False,            # GUI 앱(콘솔 창 숨김)
    disable_windowed_traceback=False,
    icon=None,                # TODO: assets/icon.ico 준비 시 지정
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Volo",
)
