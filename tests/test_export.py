"""export 단계 테스트 — SRT/VTT 포맷 유효성 + 왕복 파싱 + 결정성.

검증 대상(PRD F4/F7 수용 기준 + boundary-checks B/C):
- B/AC4.1 SRT 구조: index(1부터 연속) → HH:MM:SS,mmm --> HH:MM:SS,mmm → 1+ 텍스트 줄 → 빈 줄.
- AC4.2 타임코드 쉼표 구분 + 밀리초 3자리 + 0패딩, 초→타임코드 라운드트립(버림 단위 ±1ms).
- AC4.3 UTF-8(BOM 옵션), 표준 파서 재파싱 시 cue 수/타임/텍스트 보존(한글 깨지지 않음).
- AC4.4 인덱스 1부터 연속, 시간 오름차순.
- C/AC7.1 VTT: WEBVTT 헤더 시작 + 점(.) 구분자 + 밀리초 3자리.
- AC7.2 동일 list[Subtitle] 에서 SRT/VTT cue 수·타임·텍스트 일치.
- 번역 줄 출력(lang=...) 및 미지원 포맷 오류.

파일 쓰기/재읽기 왕복 검증은 tmp_path(pytest 기본 fixture)를 쓴다.
import 은 stdlib + volo_engine.export/models/errors 만(conftest 헬퍼 사용).
"""

from __future__ import annotations

import re

import pytest
from conftest import make_subtitle, parse_srt, parse_vtt

from volo_engine.errors import VoloExportError
from volo_engine.export import export, format_timestamp, render_srt, render_vtt


# --------------------------------------------------------------------------- #
# format_timestamp
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0.0, "00:00:00,000"),
        (1.0, "00:00:01,000"),
        (3.2, "00:00:03,200"),
        (61.5, "00:01:01,500"),
        (3661.5, "01:01:01,500"),
        (-5.0, "00:00:00,000"),  # 음수는 0으로 클램프
    ],
)
def test_format_timestamp_srt(seconds, expected):
    assert format_timestamp(seconds, sep=",") == expected


def test_format_timestamp_vtt_separator():
    assert format_timestamp(3.2, sep=".") == "00:00:03.200"


def test_format_timestamp_truncates_not_rounds():
    """밀리초는 버림(truncate). 0.9999s → 999ms(반올림이면 1000)."""
    assert format_timestamp(0.9999, sep=",") == "00:00:00,999"


def test_format_timestamp_roundtrip_within_1ms():
    """AC4.2: 초→타임코드→초 라운드트립이 버림 단위(<=1ms)에서 일치."""
    for seconds in (0.0, 0.123, 1.0, 59.999, 3661.456):
        tc = format_timestamp(seconds, sep=",")
        m = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", tc)
        assert m
        back = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000.0
        assert abs(back - seconds) <= 0.001 + 1e-9, f"{seconds} -> {tc} -> {back}"


# --------------------------------------------------------------------------- #
# SRT 구조 / 왕복
# --------------------------------------------------------------------------- #


def _sample_subs():
    return [
        make_subtitle(1, 1.0, 3.2, ["첫 번째 자막 줄", "두 번째 자막 줄"]),
        make_subtitle(2, 3.3, 5.0, ["다음 자막"]),
        make_subtitle(3, 5.1, 7.25, ["세 번째", "한글 깨짐 없는지"]),
    ]


def test_render_srt_structure():
    """AC4.1: index → 타임코드 → 줄 → 빈 줄 구조."""
    out = render_srt(_sample_subs())
    blocks = [b for b in out.split("\n\n") if b.strip()]
    assert len(blocks) == 3
    first = blocks[0].split("\n")
    assert first[0] == "1"
    assert first[1] == "00:00:01,000 --> 00:00:03,200"
    assert first[2] == "첫 번째 자막 줄"
    assert first[3] == "두 번째 자막 줄"
    # 종료자: 마지막 cue 뒤에도 빈 줄(연속 newline)로 끝난다.
    assert out.endswith("\n\n")


def test_srt_index_one_based_contiguous_ignores_subtitle_index():
    """AC4.4: 출력 인덱스는 1부터 연속(Subtitle.index 값과 무관하게 재부여)."""
    subs = [
        make_subtitle(99, 0.0, 1.0, ["a"]),
        make_subtitle(5, 1.1, 2.0, ["b"]),
        make_subtitle(0, 2.1, 3.0, ["c"]),
    ]
    cues = parse_srt(render_srt(subs))
    assert [c.index for c in cues] == [1, 2, 3]


def test_srt_roundtrip_preserves_content(tmp_path):
    """AC4.3: 파일로 쓴 뒤 다시 파싱하면 cue 수/타임/텍스트가 보존된다(한글 포함)."""
    subs = _sample_subs()
    out_file = tmp_path / "clip.srt"
    written = export(subs, "srt", str(out_file))
    assert written
    text = out_file.read_text(encoding="utf-8")
    cues = parse_srt(text)
    assert len(cues) == len(subs)
    for parsed, original in zip(cues, subs):
        assert abs(parsed.start - original.start) <= 0.001 + 1e-9
        assert abs(parsed.end - original.end) <= 0.001 + 1e-9
        assert parsed.lines == original.lines


def test_srt_utf8_no_bom_by_default(tmp_path):
    """기본은 BOM 없는 UTF-8(프리미어 권장)."""
    out_file = tmp_path / "nobom.srt"
    export(_sample_subs(), "srt", str(out_file))
    raw = out_file.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "기본 출력에 BOM 이 있으면 안 됨"


def test_srt_utf8_bom_option(tmp_path):
    """bom=True 면 UTF-8 BOM 선행."""
    out_file = tmp_path / "bom.srt"
    export(_sample_subs(), "srt", str(out_file), bom=True)
    raw = out_file.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "bom=True 인데 BOM 없음"


def test_srt_timecode_format_strict():
    """AC4.2: 모든 타임코드 줄이 HH:MM:SS,mmm --> HH:MM:SS,mmm 형식."""
    out = render_srt(_sample_subs())
    tc_lines = [ln for ln in out.split("\n") if "-->" in ln]
    pat = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$")
    for ln in tc_lines:
        assert pat.match(ln), f"타임코드 형식 위반: {ln!r}"


def test_empty_subtitles_srt_is_empty_string():
    """빈 입력이면 빈 SRT 문자열(오류 아님)."""
    assert render_srt([]) == ""


def test_crlf_newline_option():
    """newline='\\r\\n' 면 CRLF 로 출력."""
    out = render_srt(_sample_subs(), newline="\r\n")
    assert "\r\n" in out
    # 파서는 CRLF 도 정규화해 동일하게 파싱.
    cues = parse_srt(out)
    assert len(cues) == 3


# --------------------------------------------------------------------------- #
# VTT 구조 / 일치
# --------------------------------------------------------------------------- #


def test_render_vtt_header_and_dot_separator():
    """AC7.1: WEBVTT 헤더로 시작, 타임코드 점(.) 구분자, 밀리초 3자리."""
    out = render_vtt(_sample_subs())
    assert out.startswith("WEBVTT")
    tc_lines = [ln for ln in out.split("\n") if "-->" in ln]
    pat = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}$")
    for ln in tc_lines:
        assert pat.match(ln), f"VTT 타임코드 형식 위반: {ln!r}"


def test_srt_vtt_same_cues_match():
    """AC7.2: 동일 list[Subtitle] 의 SRT/VTT cue 수·타임·텍스트가 일치."""
    subs = _sample_subs()
    srt_cues = parse_srt(render_srt(subs))
    vtt_cues = parse_vtt(render_vtt(subs))
    assert len(srt_cues) == len(vtt_cues) == len(subs)
    for s, v in zip(srt_cues, vtt_cues):
        assert abs(s.start - v.start) <= 0.001 + 1e-9
        assert abs(s.end - v.end) <= 0.001 + 1e-9
        assert s.lines == v.lines


def test_export_vtt_file_roundtrip(tmp_path):
    out_file = tmp_path / "clip.vtt"
    export(_sample_subs(), "vtt", str(out_file))
    text = out_file.read_text(encoding="utf-8")
    cues = parse_vtt(text)
    assert len(cues) == 3


# --------------------------------------------------------------------------- #
# 번역 줄 출력 / 미지원 포맷
# --------------------------------------------------------------------------- #


def test_export_translation_lines():
    """lang 지정 시 translation[lang] 줄로 출력."""
    subs = [
        make_subtitle(1, 0.0, 2.0, ["안녕하세요"], translation={"en": ["Hello"]}),
        make_subtitle(2, 2.1, 4.0, ["반갑습니다"], translation={"en": ["Nice to meet you"]}),
    ]
    cues = parse_srt(render_srt(subs, lang="en"))
    assert cues[0].lines == ["Hello"]
    assert cues[1].lines == ["Nice to meet you"]


def test_export_missing_translation_yields_empty_text():
    """번역이 없는 cue 를 lang 으로 출력하면 텍스트 없는 cue(타임코드만)."""
    subs = [make_subtitle(1, 0.0, 2.0, ["원본"], translation=None)]
    out = render_srt(subs, lang="en")
    cues = parse_srt(out)
    assert len(cues) == 1
    assert cues[0].lines == [] or cues[0].lines == [""]


@pytest.mark.parametrize("fmt", ["txt", "ass", "", "SRTT"])
def test_unsupported_format_raises(tmp_path, fmt):
    """미지원 포맷이면 VoloExportError."""
    with pytest.raises(VoloExportError):
        export(_sample_subs(), fmt, str(tmp_path / "x.out"))


def test_format_case_insensitive(tmp_path):
    """포맷 대소문자 무시('SRT' 허용)."""
    out_file = tmp_path / "upper.srt"
    written = export(_sample_subs(), "SRT", str(out_file))
    assert written
    assert out_file.exists()


def test_embedded_newlines_do_not_break_structure():
    """줄 안에 내장 개행이 있어도 cue 구조(빈 줄 구분)를 깨지 않는다."""
    subs = [make_subtitle(1, 0.0, 2.0, ["줄1\n줄2"])]
    out = render_srt(subs)
    cues = parse_srt(out)
    assert len(cues) == 1
    assert cues[0].lines == ["줄1", "줄2"]


def test_export_determinism():
    """결정성: 동일 입력 → 동일 출력 바이트."""
    subs = _sample_subs()
    assert render_srt(subs) == render_srt(subs)
    assert render_vtt(subs) == render_vtt(subs)
