# Volo 캐노니컬 데이터 모델 (단일 진실 원천)

이 문서는 `volo_engine/models.py`의 기준이다. 모든 파이프라인 단계는 이 자료형으로만 데이터를 주고받는다.
엔진·CLI·앱·QA가 모두 이 정의를 참조한다. 변경 시 영향 모듈을 통지한다.

## 공통 규약
- **타임스탬프 단위**: 초(seconds), `float`. SRT 변환 시에만 `HH:MM:SS,mmm`으로 포맷.
- **텍스트 인코딩**: UTF-8.
- **언어 코드**: ISO-639-1 (`ko`, `en`, `ja` …).
- dataclass 사용, 명시적 타입 힌트, nullability를 `| None`으로 명확히.

## 자료형

```python
from dataclasses import dataclass, field

@dataclass
class Word:
    text: str
    start: float          # 초
    end: float            # 초
    prob: float           # 0~1, 단어 신뢰도

@dataclass
class Segment:
    """Whisper 원시 전사 단위 (세그멘테이션 전)."""
    index: int
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None
    lang: str = "ko"

@dataclass
class Transcript:
    """전사 전체 결과."""
    language: str          # 감지/지정 언어
    duration: float        # 전체 길이(초)
    segments: list[Segment] = field(default_factory=list)  # 전사 순서. transcribe가 항상 채움

@dataclass
class Subtitle:
    """세그멘테이션 후 최종 자막 cue (화면에 한 번에 뜨는 단위)."""
    index: int             # 1부터
    start: float
    end: float
    lines: list[str]       # 1~2줄
    lang: str = "ko"
    style: str | None = None      # 적용된 스타일 프리셋 이름
    translation: dict[str, list[str]] | None = None  # {"en": ["..."]}
    speaker: str | None = None    # 화자 라벨(선택, 화자분리 P3 예약 필드)

@dataclass
class StylePreset:
    name: str
    font_family: str
    font_size: int
    primary_color: str     # "#RRGGBB"
    outline_color: str
    position: str          # "bottom" | "top" | "center"
```

## 옵션/설정 자료형

```python
@dataclass
class TranscribeOptions:
    model_size: str = "large-v3"    # "medium" | "large-v3" 등
    language: str | None = "ko"      # None이면 자동감지
    device: str = "auto"             # "auto" | "cuda" | "cpu"
    compute_type: str = "auto"       # "float16" | "int8" 등
    word_timestamps: bool = True
    vad_filter: bool = True
    beam_size: int = 5
    # 한국어 품질 / 환각·반복 억제 (subtitle-domain §2)
    initial_prompt: str | None = None            # 고유명사·도메인 어휘 인식 힌트
    condition_on_previous_text: bool = False     # 자막 안정성↑(반복/드리프트↓)
    temperature: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)  # 폴백
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    hallucination_silence_threshold: float | None = 2.0

@dataclass
class SegmentRules:
    max_chars_per_line: int = 20     # 한국어 권장 16~20
    max_lines: int = 2
    max_cps: float = 17.0            # characters per second 상한
    min_duration: float = 1.0        # cue 최소 표시(초)
    max_duration: float = 7.0        # cue 최대 표시(초)
    min_gap: float = 0.08            # cue 간 최소 간격(초)
```

## 단계별 입출력 계약 (요약)
| 단계 | 입력 | 출력 |
|------|------|------|
| extract_audio | video_path: str | wav_path: str |
| transcribe | wav_path, TranscribeOptions | Transcript |
| correct | Transcript, glossary: dict[str,str] | Transcript |
| segment | Transcript, SegmentRules | list[Subtitle] |
| translate | list[Subtitle], target_lang: str | list[Subtitle] (translation 채움) |
| apply_style | list[Subtitle], StylezPreset | list[Subtitle] (style 채움) |
| export | list[Subtitle], fmt: str, out_path | out_path |

## 불변식 (QA가 검증)
- `Subtitle.start < Subtitle.end`, 인접 cue는 `next.start >= prev.end`(겹침 금지).
- `index`는 1부터 연속.
- `lines`는 1~2개, 각 줄 길이 ≤ `max_chars_per_line`(예외는 단어 분할 불가 시).
- 모든 타임스탬프 ≥ 0, `end ≤ Transcript.duration`.
