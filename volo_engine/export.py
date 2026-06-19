"""자막 내보내기 — SRT(주력)·VTT writer + 스타일 사이드카.

세그멘테이션·번역·스타일 적용이 끝난 ``list[Subtitle]`` 을 프리미어가 임포트할 수 있는
자막 파일(``.srt`` / ``.vtt``)로 직렬화한다. 이 모듈은 **결정적**이며 **stdlib만** 사용한다
(``faster_whisper`` / ``ffmpeg`` 등 무거운 의존성 import 금지). 동일 입력은 항상 동일 출력
바이트를 낸다 → QA가 pytest로 불변식·골든 파일을 검증할 수 있다.

포맷 규격(``references/subtitle-domain.md`` §7):

SRT (주력 — 프리미어 캡션 트랙 직접 임포트)::

    1
    00:00:01,000 --> 00:00:03,200
    첫 번째 자막 줄
    두 번째 자막 줄
    <빈 줄>
    2
    ...

    - 인덱스(1부터) → 타임코드 ``HH:MM:SS,mmm``(쉼표 구분, 밀리초 3자리)
    - cue 줄들 → 빈 줄로 cue 구분 → UTF-8.

VTT::

    WEBVTT
    <빈 줄>
    00:00:01.000 --> 00:00:03.200
    첫 번째 자막

    - 파일 시작 ``WEBVTT`` 헤더, 타임코드 구분자가 점(``.``).

SRT/VTT 는 스타일을 담지 못하므로, 스타일 정보는 별도 사이드카(``name.style.json``)로
함께 내보낼 수 있다(:func:`write_style_sidecar`).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .config import SUPPORTED_EXPORT_FORMATS
from .errors import VoloExportError
from .models import StylePreset, Subtitle

__all__ = [
    "export",
    "format_timestamp",
    "render_srt",
    "render_vtt",
    "write_style_sidecar",
]


# --------------------------------------------------------------------------- #
# 타임코드 포맷
# --------------------------------------------------------------------------- #


def format_timestamp(seconds: float, *, sep: str = ",") -> str:
    """초 단위 float 를 ``HH:MM:SS<sep>mmm`` 타임코드 문자열로 변환한다.

    내부 표현(초 단위 float)을 자막 포맷의 타임코드로 직렬화하는 단일 지점이다.
    밀리초는 반올림 없이 버림(truncate)하여 결정성을 보장한다. 음수 입력은 0으로 클램프한다.

    Args:
        seconds: 시각(초). 음수는 0으로 취급한다.
        sep: 초와 밀리초 사이 구분자. SRT 는 ``","``, VTT 는 ``"."``.

    Returns:
        ``"HH:MM:SS,mmm"``(SRT) 또는 ``"HH:MM:SS.mmm"``(VTT) 형식의 타임코드.

    Examples:
        >>> format_timestamp(1.0)
        '00:00:01,000'
        >>> format_timestamp(3.2, sep=".")
        '00:00:03.200'
        >>> format_timestamp(3661.5)
        '01:01:01,500'
    """
    if seconds < 0.0:
        seconds = 0.0
    # 밀리초로 환산(버림) 후 시/분/초/밀리초로 분해 → 부동소수 누적오차 회피.
    total_ms = int(seconds * 1000.0)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


# --------------------------------------------------------------------------- #
# cue 텍스트 선택(원본 / 번역)
# --------------------------------------------------------------------------- #


def _cue_lines(sub: Subtitle, lang: str | None) -> list[str]:
    """cue 에서 출력할 줄 리스트를 선택한다(원본 또는 지정 언어 번역).

    Args:
        sub: 대상 자막 cue.
        lang: ``None`` 이면 원본 ``sub.lines``. 언어 코드면 ``sub.translation[lang]``.
            번역이 없거나 해당 언어 키가 없으면 빈 cue(빈 리스트)를 반환한다
            (해당 cue 는 타임코드만 있고 텍스트가 비게 됨 — 호출자 정책에 위임).

    Returns:
        출력할 텍스트 줄 리스트. 후행 개행이 섞이지 않도록 각 줄의 줄바꿈 문자는 제거한다.
    """
    if lang is None:
        raw = sub.lines
    else:
        translation = sub.translation or {}
        raw = translation.get(lang, [])
    # 줄 안에 내장된 개행이 cue 구조를 깨지 않도록 정규화한다.
    cleaned: list[str] = []
    for line in raw:
        for piece in line.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            cleaned.append(piece)
    return cleaned


# --------------------------------------------------------------------------- #
# 포맷별 렌더러(순수 문자열 생성 — 파일 I/O 없음)
# --------------------------------------------------------------------------- #


def render_srt(
    subtitles: list[Subtitle],
    *,
    lang: str | None = None,
    newline: str = "\n",
) -> str:
    """``list[Subtitle]`` 을 SRT 문자열로 렌더링한다(파일 쓰기 없음).

    cue 인덱스는 ``Subtitle.index`` 를 신뢰하지 않고 **출력 순서대로 1부터 재부여**한다
    (번역 출력 등에서 일부 cue 가 비어도 SRT 인덱스 연속성을 보장).

    Args:
        subtitles: 출력할 자막 cue 리스트(이미 정렬·세그멘테이션된 상태).
        lang: ``None`` 이면 원본 줄, 언어 코드면 해당 번역 줄로 출력.
        newline: 줄 끝 문자(``"\\n"`` 또는 ``"\\r\\n"``). 프리미어는 둘 다 허용.

    Returns:
        SRT 형식 전체 문자열(마지막 cue 뒤에도 빈 줄 종료자 포함).
    """
    blocks: list[str] = []
    for out_index, sub in enumerate(subtitles, start=1):
        lines = _cue_lines(sub, lang)
        start_tc = format_timestamp(sub.start, sep=",")
        end_tc = format_timestamp(sub.end, sep=",")
        block_lines = [str(out_index), f"{start_tc} --> {end_tc}", *lines]
        blocks.append(newline.join(block_lines))
    if not blocks:
        return ""
    # cue 사이/끝을 빈 줄로 구분: 각 블록은 빈 줄(연속 newline 2개)로 구분되고
    # 마지막 cue 뒤에도 빈 줄 종료자를 둔다.
    separator = newline + newline
    return separator.join(blocks) + separator


def render_vtt(
    subtitles: list[Subtitle],
    *,
    lang: str | None = None,
    newline: str = "\n",
) -> str:
    """``list[Subtitle]`` 을 WebVTT 문자열로 렌더링한다(파일 쓰기 없음).

    파일 시작에 ``WEBVTT`` 헤더를 두고, 타임코드 구분자로 점(``.``)을 사용한다.
    VTT cue 는 인덱스 번호가 선택사항이므로 생략한다(타임코드 줄부터 시작).

    Args:
        subtitles: 출력할 자막 cue 리스트.
        lang: ``None`` 이면 원본 줄, 언어 코드면 해당 번역 줄로 출력.
        newline: 줄 끝 문자(``"\\n"`` 또는 ``"\\r\\n"``).

    Returns:
        ``WEBVTT`` 헤더로 시작하는 VTT 형식 전체 문자열.
    """
    parts: list[str] = ["WEBVTT", ""]  # 헤더 + 헤더 뒤 빈 줄
    for sub in subtitles:
        lines = _cue_lines(sub, lang)
        start_tc = format_timestamp(sub.start, sep=".")
        end_tc = format_timestamp(sub.end, sep=".")
        parts.append(f"{start_tc} --> {end_tc}")
        parts.extend(lines)
        parts.append("")  # cue 구분 빈 줄
    return newline.join(parts) + newline


# --------------------------------------------------------------------------- #
# 공개 진입점
# --------------------------------------------------------------------------- #

# 렌더러 디스패치 테이블(포맷 → 문자열 생성 함수). config.SUPPORTED_EXPORT_FORMATS 와 정합.
_RENDERERS = {
    "srt": render_srt,
    "vtt": render_vtt,
}


def export(
    subtitles: list[Subtitle],
    fmt: str,
    out_path: str,
    *,
    lang: str | None = None,
    bom: bool = False,
    newline: str = "\n",
) -> str:
    """``list[Subtitle]`` 을 SRT/VTT 자막 파일로 내보낸다.

    ARCHITECTURE §4 의 계약 시그니처를 그대로 구현한다. 결정적·stdlib 전용이며,
    동일 입력은 동일 파일 바이트를 생성한다.

    Args:
        subtitles: 내보낼 자막 cue 리스트. 빈 리스트면 헤더/빈 파일을 쓴다(오류 아님).
        fmt: 출력 포맷. ``"srt"`` 또는 ``"vtt"``(대소문자 무시). 그 외는 :class:`VoloExportError`.
        out_path: 출력 파일 경로. 상위 디렉토리가 없으면 생성한다.
        lang: ``None`` 이면 원본(``Subtitle.lines``)을, 언어 코드면 해당 번역
            (``Subtitle.translation[lang]``)을 출력한다(다국어 분리 파일).
        bom: UTF-8 BOM 선행 여부. 일부 플레이어 호환용. 기본 ``False``(프리미어 권장).
        newline: 줄 끝 문자(``"\\n"`` 또는 ``"\\r\\n"``). 프리미어는 둘 다 허용.

    Returns:
        실제로 쓴 출력 파일의 절대 경로.

    Raises:
        VoloExportError: 미지원 포맷, 디렉토리 생성/파일 쓰기 실패 시.
    """
    fmt_norm = fmt.strip().lower()
    if fmt_norm not in SUPPORTED_EXPORT_FORMATS or fmt_norm not in _RENDERERS:
        supported = ", ".join(SUPPORTED_EXPORT_FORMATS)
        raise VoloExportError(
            f"지원하지 않는 자막 포맷입니다: {fmt!r}",
            hint=f"지원 포맷: {supported}",
        )

    renderer = _RENDERERS[fmt_norm]
    content = renderer(subtitles, lang=lang, newline=newline)

    # 상위 디렉토리 보장.
    parent = os.path.dirname(os.path.abspath(out_path))
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise VoloExportError(
            f"출력 디렉토리를 만들 수 없습니다: {parent}",
            hint=str(exc),
        ) from exc

    # UTF-8(옵션으로 BOM). newline 은 렌더러가 이미 삽입했으므로 변환 비활성(newline="").
    encoding = "utf-8-sig" if bom else "utf-8"
    try:
        with open(out_path, "w", encoding=encoding, newline="") as fh:
            fh.write(content)
    except OSError as exc:
        raise VoloExportError(
            f"자막 파일을 쓸 수 없습니다: {out_path}",
            hint=str(exc),
        ) from exc

    return os.path.abspath(out_path)


# --------------------------------------------------------------------------- #
# 스타일 사이드카(name.style.json)
# --------------------------------------------------------------------------- #


def write_style_sidecar(preset: StylePreset, out_path: str) -> str:
    """스타일 프리셋을 자막 옆 사이드카 JSON(``name.style.json``)으로 내보낸다.

    SRT/VTT 는 스타일을 담지 못하므로, 적용된 :class:`StylePreset` 을 별도 JSON 으로
    함께 출력해 프리미어 캡션 트랙 적용 가이드/미리보기의 근거로 쓴다(``subtitle-domain.md`` §7·§8).

    경로 규칙: 자막 출력 경로의 확장자를 ``.style.json`` 으로 치환한다.
    예) ``out/clip.srt`` → ``out/clip.style.json``.

    Args:
        preset: 직렬화할 스타일 프리셋.
        out_path: 기준 출력 경로(보통 :func:`export` 의 ``out_path``). 확장자만 교체된다.

    Returns:
        실제로 쓴 사이드카 파일의 절대 경로.

    Raises:
        VoloExportError: 디렉토리 생성/파일 쓰기 실패 시.
    """
    root, _ = os.path.splitext(os.path.abspath(out_path))
    sidecar_path = f"{root}.style.json"

    parent = os.path.dirname(sidecar_path)
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise VoloExportError(
            f"사이드카 디렉토리를 만들 수 없습니다: {parent}",
            hint=str(exc),
        ) from exc

    # 결정적 출력: 키 정렬 + UTF-8(비ASCII 보존, ensure_ascii=False).
    payload = asdict(preset)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with open(sidecar_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    except OSError as exc:
        raise VoloExportError(
            f"스타일 사이드카를 쓸 수 없습니다: {sidecar_path}",
            hint=str(exc),
        ) from exc

    return sidecar_path
