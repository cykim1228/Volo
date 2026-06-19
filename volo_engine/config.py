"""Volo 엔진 기본 경로/상수/기본 옵션 팩토리.

기본 ``SegmentRules`` / ``TranscribeOptions`` 를 생성하고, 모델 캐시/프리셋 경로 등
공용 상수를 정의한다. 이 모듈도 stdlib만 사용한다(무거운 의존성 import 금지).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .models import SegmentRules, TranscribeOptions

__all__ = [
    "ENGINE_VERSION",
    "DEFAULT_MODEL_SIZE",
    "DEFAULT_LANGUAGE",
    "AUDIO_SAMPLE_RATE",
    "AUDIO_CHANNELS",
    "SUPPORTED_EXPORT_FORMATS",
    "SUPPORTED_INPUT_SUFFIXES",
    "PROJECT_ROOT",
    "PRESETS_DIR",
    "model_cache_dir",
    "default_transcribe_options",
    "default_segment_rules",
]

# 엔진 코어 버전(패키지 버전과 별개로 엔진 계약 버전 추적용).
ENGINE_VERSION = "0.1.0"

# --- STT / 오디오 상수 ----------------------------------------------------- #
DEFAULT_MODEL_SIZE = "large-v3"
DEFAULT_LANGUAGE = "ko"

# Whisper 선호 입력 포맷: 16kHz mono PCM.
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1

# --- 포맷/입력 ------------------------------------------------------------- #
SUPPORTED_EXPORT_FORMATS: tuple[str, ...] = ("srt", "vtt")

# 오디오 추출이 받아들이는 입력 컨테이너(검증용; 그 외도 ffmpeg가 처리할 수 있음).
SUPPORTED_INPUT_SUFFIXES: tuple[str, ...] = (
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
    ".aac",
)

# --- 경로 ------------------------------------------------------------------ #
# 일반 실행: <root>/volo_engine/config.py → PROJECT_ROOT = <root>.
# PyInstaller 번들(frozen): 동봉 데이터가 sys._MEIPASS 아래에 있으므로 그 경로를 루트로 쓴다
#   (spec 의 datas=[("assets/presets", "assets/presets")] 와 일치). 그래야 .exe 에서 프리셋 로드.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRESETS_DIR = PROJECT_ROOT / "assets" / "presets"


def model_cache_dir() -> Path:
    """faster-whisper / huggingface 모델 캐시 디렉토리를 반환한다.

    우선순위:
        1. 환경변수 ``VOLO_MODEL_CACHE``
        2. 환경변수 ``HF_HOME``
        3. 기본 ``~/.cache/huggingface``

    실제 디렉토리 생성은 호출자(transcribe 로더)가 담당한다. 여기서는 경로만 계산한다.
    """
    env_cache = os.environ.get("VOLO_MODEL_CACHE")
    if env_cache:
        return Path(env_cache)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home)
    return Path.home() / ".cache" / "huggingface"


def default_transcribe_options() -> TranscribeOptions:
    """기본 :class:`TranscribeOptions` 를 생성한다.

    한국어 ``large-v3``, device/compute_type ``auto``, 단어 타임스탬프 활성.
    """
    return TranscribeOptions(
        model_size=DEFAULT_MODEL_SIZE,
        language=DEFAULT_LANGUAGE,
        device="auto",
        compute_type="auto",
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )


def default_segment_rules() -> SegmentRules:
    """기본 :class:`SegmentRules` 를 생성한다(한국어 자막 가독성 기준)."""
    return SegmentRules(
        max_chars_per_line=20,
        max_lines=2,
        max_cps=17.0,
        min_duration=1.0,
        max_duration=7.0,
        min_gap=0.08,
    )
