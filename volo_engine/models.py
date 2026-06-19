"""Volo 캐노니컬 데이터 모델 — 단일 진실 원천.

이 모듈은 ``.claude/skills/volo-architecture/references/data-model.md``를 실제 코드로
구현한 것이다. 자막 파이프라인의 모든 단계(audio → transcribe → correct → segment →
translate → style → export)는 **오직 이 자료형으로만** 데이터를 주고받는다.
엔진·CLI·앱·QA가 모두 이 정의를 참조한다. 변경 시 영향 모듈(engine/cli/app/tests)을 통지한다.

공통 규약
---------
- **타임스탬프 단위**: 초(seconds), ``float``. SRT/VTT 변환 시에만 ``HH:MM:SS,mmm`` /
  ``HH:MM:SS.mmm`` 으로 포맷한다. 내부 표현은 항상 초 단위 float.
- **텍스트 인코딩**: UTF-8.
- **언어 코드**: ISO-639-1 (``"ko"``, ``"en"``, ``"ja"`` …).
- nullability는 ``| None`` 으로 명확히 한다.

주의
----
이 모듈은 의도적으로 **가벼운(stdlib만)** 모듈이다. ``faster_whisper`` / ``ffmpeg`` 등
무거운 의존성을 import 하지 않는다. 테스트는 ``models`` / ``segment`` / ``export`` 만으로
실행 가능해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "Word",
    "Segment",
    "Transcript",
    "Subtitle",
    "StylePreset",
    "TranscribeOptions",
    "SegmentRules",
]


# --------------------------------------------------------------------------- #
# 전사(transcribe) 단계 자료형
# --------------------------------------------------------------------------- #


@dataclass
class Word:
    """단어 단위 전사 결과(단어 타임스탬프).

    faster-whisper 의 ``word_timestamps=True`` 산출물에서 채워진다. 세그멘테이션은
    가능하면 ``Segment`` 가 아니라 이 ``Word`` 시퀀스를 사용해 cue 타이밍을 정밀하게 만든다.

    Attributes:
        text: 단어 텍스트(선행/후행 공백 포함될 수 있음 — Whisper 관례).
        start: 단어 시작 시각(초).
        end: 단어 끝 시각(초). ``start <= end`` 불변.
        prob: 단어 신뢰도, ``0.0 ~ 1.0``.
    """

    text: str
    start: float  # 초
    end: float  # 초
    prob: float  # 0~1, 단어 신뢰도


@dataclass
class Segment:
    """Whisper 원시 전사 단위(문장 단위, 세그멘테이션 전).

    Whisper 가 내보내는 길거나 들쭉날쭉한 전사 조각이다. 화면 표시에 적합한 자막 cue는
    아니며, ``segment`` 단계에서 ``Subtitle`` 로 재구성된다.

    Attributes:
        index: 0 또는 1 기반의 원시 세그먼트 순번(전사 순서). cue 인덱스와 무관.
        start: 세그먼트 시작 시각(초).
        end: 세그먼트 끝 시각(초).
        text: 세그먼트 전체 텍스트.
        words: 단어 타임스탬프 리스트. ``word_timestamps=False`` 면 빈 리스트.
        speaker: 화자 라벨(선택, 화자 분리 기능). 기본 ``None``.
        lang: 세그먼트 언어 코드(ISO-639-1). 기본 ``"ko"``.
    """

    index: int
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None
    lang: str = "ko"


@dataclass
class Transcript:
    """전사 전체 결과(transcribe 단계 산출).

    Attributes:
        language: 감지되었거나 지정된 언어 코드(ISO-639-1).
        duration: 오디오 전체 길이(초). 모든 cue의 ``end`` 는 이 값을 넘지 않아야 한다.
        segments: 원시 세그먼트 리스트(전사 순서).
    """

    language: str  # 감지/지정 언어
    duration: float  # 전체 길이(초)
    segments: list[Segment] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 세그멘테이션 이후 자료형
# --------------------------------------------------------------------------- #


@dataclass
class Subtitle:
    """세그멘테이션 후 최종 자막 cue(화면에 한 번에 뜨는 단위).

    파이프라인의 segment 단계 이후 모든 단계(translate / apply_style / export)가
    주고받는 핵심 자료형이다.

    불변식(QA가 검증, data-model §불변식):
        - ``start < end``
        - 인접 cue는 ``next.start >= prev.end`` (겹침 금지)
        - ``index`` 는 1부터 연속
        - ``lines`` 는 1~2개, 각 줄 길이 <= ``SegmentRules.max_chars_per_line``
          (단어 분할 불가 예외 허용)
        - 모든 타임스탬프 >= 0, ``end <= Transcript.duration``

    Attributes:
        index: cue 순번, **1부터 연속**.
        start: cue 표시 시작 시각(초).
        end: cue 표시 끝 시각(초).
        lines: 화면에 표시되는 줄들(1~2줄). 원본 언어(``lang``) 텍스트.
        lang: 원본 자막 언어 코드(ISO-639-1). 기본 ``"ko"``.
        style: 적용된 스타일 프리셋 이름. ``apply_style`` 전에는 ``None``.
        translation: 언어별 번역 줄 매핑. 예: ``{"en": ["line1", "line2"]}``.
            ``translate`` 전에는 ``None``. 타임코드는 원본과 공유한다.
        speaker: 화자 라벨(선택). 기본 ``None``.
    """

    index: int  # 1부터
    start: float
    end: float
    lines: list[str]  # 1~2줄
    lang: str = "ko"
    style: str | None = None  # 적용된 스타일 프리셋 이름
    translation: dict[str, list[str]] | None = None  # {"en": ["..."]}
    speaker: str | None = None


# --------------------------------------------------------------------------- #
# 스타일 프리셋
# --------------------------------------------------------------------------- #


@dataclass
class StylePreset:
    """자막 스타일 프리셋(폰트/색/위치 묶음).

    SRT/VTT 는 스타일을 담지 못하므로, 프리셋은 export 시 사이드카(``name.style.json``)로
    출력되고 프리미어 캡션 트랙 적용 가이드의 근거가 된다. ``assets/presets/`` 에 JSON으로 저장.

    Attributes:
        name: 프리셋 식별 이름(예: ``"default"``, ``"youtube"``, ``"interview"``).
        font_family: 폰트 패밀리명.
        font_size: 폰트 크기(pt).
        primary_color: 본문 색상, ``"#RRGGBB"``.
        outline_color: 외곽선 색상, ``"#RRGGBB"``.
        position: 자막 위치. ``"bottom"`` | ``"top"`` | ``"center"``.
    """

    name: str
    font_family: str
    font_size: int
    primary_color: str  # "#RRGGBB"
    outline_color: str  # "#RRGGBB"
    position: str  # "bottom" | "top" | "center"


# --------------------------------------------------------------------------- #
# 옵션 / 설정 자료형
# --------------------------------------------------------------------------- #


@dataclass
class TranscribeOptions:
    """전사(transcribe) 단계 옵션.

    기본값 팩토리는 ``volo_engine.config.default_transcribe_options`` 를 사용한다.

    Attributes:
        model_size: Whisper 모델 크기. ``"medium"`` | ``"large-v3"`` 등.
            기본 ``"large-v3"`` (한국어 정확도 최상).
        language: 전사 언어 코드(ISO-639-1). ``None`` 이면 자동감지. 기본 ``"ko"``.
        device: 추론 디바이스. ``"auto"`` | ``"cuda"`` | ``"cpu"``.
            ``"auto"`` 면 CUDA 가용 시 GPU, 아니면 CPU.
        compute_type: 연산 정밀도. ``"auto"`` | ``"float16"`` | ``"int8"`` 등.
            ``"auto"`` 면 device에 맞춰(GPU=float16, CPU=int8) 해석.
        word_timestamps: 단어 타임스탬프 산출 여부. 세그멘테이션 정밀도의 기반.
        vad_filter: 무음 구간 제거(VAD) 적용 여부. 타임스탬프 안정화.
        beam_size: 빔 서치 폭.
        initial_prompt: 인식 단계 힌트. 고유명사·브랜드명의 올바른 표기나 도메인 어휘를
            넣으면 그 방향으로 인식이 유도된다(사후 교정보다 강력). ``None`` 이면 미사용.
        condition_on_previous_text: 이전 텍스트를 다음 구간 조건으로 사용할지. 자막에서는
            ``False`` 가 반복/환각 드리프트를 줄여 더 안전(기본 ``False``).
        temperature: 디코딩 온도 폴백 시퀀스. 낮은 온도 실패 시 단계적으로 올려 재시도한다.
        compression_ratio_threshold: 출력 압축비가 이 값을 넘으면(=반복 의심) 폴백/기각.
        log_prob_threshold: 평균 로그확률이 이 값보다 낮으면 신뢰 불가로 폴백/기각.
        no_speech_threshold: 무음(no-speech) 확률이 이 값보다 높으면 해당 구간을 버린다.
        hallucination_silence_threshold: 단어 타임스탬프 사용 시, 이 길이(초) 이상의 무음
            구간에서 발생하는 환각 텍스트를 건너뛴다. ``None`` 이면 미적용.
    """

    model_size: str = "large-v3"  # "medium" | "large-v3" 등
    language: str | None = "ko"  # None이면 자동감지
    device: str = "auto"  # "auto" | "cuda" | "cpu"
    compute_type: str = "auto"  # "float16" | "int8" | "auto"
    word_timestamps: bool = True
    vad_filter: bool = True
    beam_size: int = 5
    # --- 한국어 품질 / 환각·반복 억제 ---
    initial_prompt: str | None = None
    condition_on_previous_text: bool = False
    temperature: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    hallucination_silence_threshold: float | None = 2.0


@dataclass
class SegmentRules:
    """세그멘테이션(segment) 단계 규칙 — 한국어 자막 가독성 기준.

    결정적 함수의 파라미터다. 동일 ``Transcript`` + ``SegmentRules`` 는 동일 결과를 낸다.
    기본값 팩토리는 ``volo_engine.config.default_segment_rules`` 를 사용한다.

    Attributes:
        max_chars_per_line: 한 줄 최대 글자수. 한국어 권장 16~20. 기본 20.
        max_lines: cue 최대 줄 수. 기본 2.
        max_cps: 초당 글자수(CPS) 상한. 한국어 권장 <= 12~17. 기본 17.0.
        min_duration: cue 최소 표시 시간(초). 기본 1.0.
        max_duration: cue 최대 표시 시간(초). 기본 7.0.
        min_gap: 인접 cue 사이 최소 간격(초). 깜빡임 방지. 기본 0.08.
    """

    max_chars_per_line: int = 20  # 한국어 권장 16~20
    max_lines: int = 2
    max_cps: float = 17.0  # characters per second 상한
    min_duration: float = 1.0  # cue 최소 표시(초)
    max_duration: float = 7.0  # cue 최대 표시(초)
    min_gap: float = 0.08  # cue 간 최소 간격(초)
