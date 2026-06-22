# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 스펙 — Volo 데스크톱 앱 **onefile**(단일 .exe) 빌드.

빌드:  pyinstaller packaging/volo-onefile.spec   (프로젝트 루트에서 실행)
산출:  dist/Volo.exe  (단일 실행파일 — 이 파일 하나만 받아서 더블클릭하면 실행)

onedir(packaging/volo.spec) 과의 차이:
- 모든 의존성(파이썬·Qt·ctranslate2·ffmpeg 등)을 **exe 하나**에 담는다 → 사용자는 파일 1개만 받으면 됨.
- 실행 시 임시 폴더(_MEIPASS)에 자동 추출 → **첫 기동이 느리고**(수백 MB 추출) 백신 오탐이 더 잦다.
- collect/hiddenimports 보강 로직은 onedir 과 동일(지연 import 인 imageio_ffmpeg·huggingface_hub 포함 필수).
⚠️ 빌드 후 (1) 단일 exe 실행, (2) 자막 생성 E2E(ffmpeg 동봉) 점검 필요.
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

_SPECDIR = SPECPATH  # noqa: F821 - PyInstaller 전역
_ROOT = os.path.dirname(_SPECDIR)

datas = []
binaries = []
hiddenimports = []

hiddenimports += collect_submodules("volo_engine")
hiddenimports += collect_submodules("volo_cli")
hiddenimports += collect_submodules("volo_app")

# 지연 import 라 정적 분석이 못 잡는 것 포함(미동봉 시 ffmpeg/모델다운로드 실패).
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
    except Exception as exc:
        print(f"[volo-onefile.spec] WARN: '{pkg}' collect 실패: {exc}")

hiddenimports += ["imageio_ffmpeg", "huggingface_hub"]
datas += collect_data_files("imageio_ffmpeg", includes=["binaries/*"])
datas += [(os.path.join(_ROOT, "assets", "presets"), "assets/presets")]


block_cipher = None

a = Analysis(
    [os.path.join(_SPECDIR, "volo_launcher.py")],
    pathex=[_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "onnx", "onnxruntime.quantization"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onefile: a.binaries / a.datas 를 EXE 에 직접 포함(COLLECT 없음).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Volo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,            # GUI 앱(콘솔 창 숨김)
    disable_windowed_traceback=False,
    icon=None,                # TODO: assets/icon.ico
)
