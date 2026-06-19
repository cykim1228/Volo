"""pytest 공통 설정 + 헬퍼(결정적 모듈 검증 전용).

이 파일은 ``volo_engine`` 의 **결정적 모듈만**(models/segment/export) import 한다.
무거운 의존성(faster-whisper/ffmpeg/PySide6)을 끌어오지 않으므로, 그것들이 설치돼
있지 않아도 테스트가 import·수집(collect)·실행 가능해야 한다(ARCHITECTURE §1.5 얕은
__init__ 정책).

제공 헬퍼:
- 프로젝트 루트를 ``sys.path`` 에 추가(소스 레이아웃에서 ``volo_engine`` 직접 import).
- ``make_word`` / ``make_segment`` / ``make_transcript`` / ``make_subtitle`` 팩토리.
- ``parse_srt`` / ``parse_vtt`` 왕복 파서(export 출력을 다시 구조화해 검증).
- 불변식 검사 헬퍼 ``assert_subtitle_invariants`` (segment/export 양쪽에서 재사용).

중복을 막기 위해 모든 공통 헬퍼를 여기 모은다(SKILL: tests/conftest.py 로 헬퍼 집약).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# 소스 레이아웃: 프로젝트 루트를 import 경로에 추가.
# conftest.py 는 <root>/tests/conftest.py → 루트는 한 단계 위.
# --------------------------------------------------------------------------- #
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest  # noqa: E402  (sys.path 조정 후 import)

from volo_engine.models import (  # noqa: E402
    Segment,
    SegmentRules,
    Subtitle,
    Transcript,
    Word,
)


# --------------------------------------------------------------------------- #
# 데이터 팩토리
# --------------------------------------------------------------------------- #


def make_word(text: str, start: float, end: float, prob: float = 0.9) -> Word:
    """단어 하나를 만든다."""
    return Word(text=text, start=start, end=end, prob=prob)


def make_segment(
    index: int,
    start: float,
    end: float,
    text: str,
    words: list[Word] | None = None,
    lang: str = "ko",
) -> Segment:
    """세그먼트 하나를 만든다(words 미지정이면 빈 리스트 폴백 경로)."""
    return Segment(
        index=index,
        start=start,
        end=end,
        text=text,
        words=list(words) if words else [],
        lang=lang,
    )


def make_transcript(
    segments: list[Segment],
    duration: float,
    language: str = "ko",
) -> Transcript:
    """전사 결과를 만든다."""
    return Transcript(language=language, duration=duration, segments=list(segments))


def words_from_spec(spec: list[tuple[str, float, float]]) -> list[Word]:
    """(text, start, end) 튜플 리스트에서 Word 리스트를 만든다(테스트 가독성용)."""
    return [make_word(t, s, e) for (t, s, e) in spec]


def make_subtitle(
    index: int,
    start: float,
    end: float,
    lines: list[str],
    lang: str = "ko",
    translation: dict[str, list[str]] | None = None,
) -> Subtitle:
    """자막 cue 하나를 만든다."""
    return Subtitle(
        index=index,
        start=start,
        end=end,
        lines=list(lines),
        lang=lang,
        translation=translation,
    )


# --------------------------------------------------------------------------- #
# 왕복 파서: export 출력 문자열을 구조화해 검증.
# --------------------------------------------------------------------------- #


@dataclass
class ParsedCue:
    """파싱된 cue(왕복 검증용). 타임스탬프는 초 단위 float."""

    index: int | None
    start: float
    end: float
    lines: list[str]


_SRT_TC = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})$"
)
_VTT_TC = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})$"
)


def _tc_groups_to_seconds(g: tuple[str, ...]) -> tuple[float, float]:
    start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000.0
    end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000.0
    return start, end


def parse_srt(text: str) -> list[ParsedCue]:
    """SRT 문자열을 cue 리스트로 엄격 파싱한다(표준 구조 가정).

    구조: ``index 줄`` → ``HH:MM:SS,mmm --> HH:MM:SS,mmm`` → 1+ 텍스트 줄 → 빈 줄.
    파서가 표준 구조를 강제하므로, export 출력이 표준을 어기면 여기서 드러난다.
    """
    # 줄바꿈 정규화 후 빈 줄로 블록 분리.
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b for b in re.split(r"\n[ \t]*\n", norm) if b.strip() != ""]
    cues: list[ParsedCue] = []
    for block in blocks:
        lines = block.split("\n")
        assert len(lines) >= 2, f"cue 블록은 최소 인덱스+타임코드 2줄이어야 함: {block!r}"
        idx = int(lines[0].strip())
        m = _SRT_TC.match(lines[1].strip())
        assert m is not None, f"SRT 타임코드 형식 위반: {lines[1]!r}"
        start, end = _tc_groups_to_seconds(m.groups())
        text_lines = lines[2:]
        cues.append(ParsedCue(index=idx, start=start, end=end, lines=text_lines))
    return cues


def parse_vtt(text: str) -> list[ParsedCue]:
    """VTT 문자열을 cue 리스트로 파싱한다(WEBVTT 헤더 확인 + 점 구분자)."""
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    assert norm.startswith("WEBVTT"), "VTT 는 WEBVTT 헤더로 시작해야 함"
    blocks = [b for b in re.split(r"\n[ \t]*\n", norm) if b.strip() != ""]
    cues: list[ParsedCue] = []
    for block in blocks:
        lines = block.split("\n")
        if lines and lines[0].strip() == "WEBVTT":
            # 헤더 블록(헤더 + 메타) 건너뜀.
            lines = lines[1:]
            if not lines:
                continue
        # cue 블록: 첫 줄이 타임코드(선택적 cue id 없음 가정).
        m = _VTT_TC.match(lines[0].strip())
        if m is None:
            # cue id 가 붙은 경우 다음 줄을 본다.
            if len(lines) >= 2:
                m = _VTT_TC.match(lines[1].strip())
                if m is not None:
                    lines = lines[1:]
        if m is None:
            continue
        start, end = _tc_groups_to_seconds(m.groups())
        text_lines = lines[1:]
        cues.append(ParsedCue(index=None, start=start, end=end, lines=text_lines))
    return cues


# --------------------------------------------------------------------------- #
# 불변식 검사(segment·export 공통).
# --------------------------------------------------------------------------- #


def assert_subtitle_invariants(
    subtitles: list[Subtitle], rules: SegmentRules, duration: float
) -> None:
    """data-model 불변식 I1~I5 를 cue 목록에 대해 검사한다.

    각 위반은 cue 위치·실제값을 담은 메시지로 즉시 실패시킨다(QA가 위치 추적 가능).
    줄 길이(I4)의 '단어 분할 불가 예외'(공백 없는 단일 어절이 한도 초과)는 허용한다.
    """
    prev_end: float | None = None
    for i, sub in enumerate(subtitles):
        # I1: start < end
        assert sub.start < sub.end, (
            f"[I1] cue {i} start>=end: start={sub.start} end={sub.end}"
        )
        # I3: index 1부터 연속
        assert sub.index == i + 1, (
            f"[I3] cue {i} index 불연속: index={sub.index}, 기대={i + 1}"
        )
        # I5: 타임스탬프 >= 0, end <= duration(부동소수 미세오차 허용)
        assert sub.start >= 0.0, f"[I5] cue {i} start<0: {sub.start}"
        assert sub.end >= 0.0, f"[I5] cue {i} end<0: {sub.end}"
        if duration > 0:
            assert sub.end <= duration + 1e-6, (
                f"[I5] cue {i} end>duration: end={sub.end} duration={duration}"
            )
        # I2: 인접 cue 겹침 금지
        if prev_end is not None:
            assert sub.start >= prev_end - 1e-6, (
                f"[I2] cue {i} 겹침: start={sub.start} < prev.end={prev_end}"
            )
        prev_end = sub.end
        # I4: 줄 수 1~max_lines, 각 줄 길이 <= max_chars (단어 분할 불가 예외)
        assert 1 <= len(sub.lines) <= rules.max_lines, (
            f"[I4] cue {i} 줄 수 위반: {len(sub.lines)} 줄 (max={rules.max_lines})"
        )
        for li, line in enumerate(sub.lines):
            if len(line) > rules.max_chars_per_line:
                # 공백 없는 단일 어절이면 분할 불가 예외로 허용.
                assert " " not in line.strip(), (
                    f"[I4] cue {i} 줄 {li} 길이 초과(분할 가능한데 미분할): "
                    f"{len(line)}자 > {rules.max_chars_per_line}: {line!r}"
                )


def cps_of(sub: Subtitle) -> float:
    """cue 의 CPS(공백 제외 글자수 / 표시시간)를 계산한다."""
    chars = sum(len(line.replace(" ", "")) for line in sub.lines)
    dur = sub.end - sub.start
    return chars / dur if dur > 0 else float("inf")


# --------------------------------------------------------------------------- #
# pytest fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def default_rules() -> SegmentRules:
    """기본 한국어 자막 규칙(data-model 기본값)."""
    return SegmentRules()


@pytest.fixture
def sample_transcript() -> Transcript:
    """단어 타임스탬프가 있는 한국어 전사 샘플(여러 cue 로 분할될 분량)."""
    words = words_from_spec(
        [
            ("안녕하세요", 0.0, 0.6),
            ("여러분", 0.6, 1.1),
            ("오늘은", 1.2, 1.7),
            ("자막", 1.7, 2.0),
            ("생성", 2.0, 2.3),
            ("도구를", 2.3, 2.8),
            ("소개합니다.", 2.8, 3.6),
            ("이", 4.5, 4.7),
            ("도구는", 4.7, 5.2),
            ("로컬에서", 5.2, 5.9),
            ("동작합니다.", 5.9, 6.8),
        ]
    )
    seg = make_segment(0, 0.0, 6.8, "안녕하세요 여러분 오늘은 자막 생성 도구를 소개합니다. 이 도구는 로컬에서 동작합니다.", words)
    return make_transcript([seg], duration=7.0)
