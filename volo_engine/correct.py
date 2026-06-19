"""한국어 교정 + 글로서리 치환 (correct 단계).

이 모듈은 전사(transcribe) 결과 :class:`~volo_engine.models.Transcript` 의 **텍스트만**
정리한다. 타임스탬프(``start`` / ``end`` / ``duration``)와 세그먼트 구조는 그대로 보존한다.
파이프라인 순서상 segment 단계 **이전** 에 적용되어, 더 깨끗한 텍스트로부터 cue를 만든다.

두 가지 일을 한다(둘 다 결정적·외부 의존 없음 → pytest 가능):

1. **글로서리 강제 치환**(우선): 사용자가 제공한 ``{잘못된표기: 올바른표기}`` 매핑을
   텍스트에 적용한다. 고유명사·브랜드명·전문용어의 STT 오인식을 교정한다.
2. **경량 한국어 정리**(``light_rules=True``, 기본): 반복 공백 정리, 문장부호 정규화
   등 stdlib 규칙만으로 안전하게 처리. 맞춤법/띄어쓰기 고급 교정(LLM·외부 교정기)은
   범위 밖이며 향후 선택 플러그인으로 둔다(ARCHITECTURE OQ2).

도메인 근거: ``.claude/skills/volo-engine-dev/references/subtitle-domain.md`` §5.
계약(시그니처): ``docs/ARCHITECTURE.md`` §4 (``correct`` 항목).

설계 메모
--------
- **텍스트만 수정, 타임스탬프 보존.** 단어 수가 바뀌거나 단어 분할이 달라지면 ``Word``
  타임스탬프 정렬이 깨질 수 있으므로, 경량 규칙(공백/문장부호 정리)은 **세그먼트 텍스트
  레벨에서만** 적용한다. 글로서리 치환은 토큰 길이가 바뀌어도 타임코드와 무관하므로
  세그먼트 텍스트와 개별 ``Word.text`` 양쪽에 동일하게 적용해 표기를 일치시킨다.
- **결정성.** 동일 ``Transcript`` + 동일 ``glossary`` → 동일 출력. dict 순서에 의존하지
  않도록 글로서리 키는 **긴 키 우선**으로 정렬해 적용한다(부분 겹침 방지).
- **비파괴.** 입력 ``Transcript`` 는 변경하지 않고 새 객체를 반환한다.

이 모듈은 stdlib(``re`` 등)만 사용한다.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .models import Segment, Transcript, Word

__all__ = ["correct", "correct_text", "apply_glossary"]


# --------------------------------------------------------------------------- #
# 내부 상수 / 정규식 (모듈 로드 시 1회 컴파일)
# --------------------------------------------------------------------------- #

# 연속 공백류(스페이스/탭, 단 줄바꿈은 별도 처리)를 하나의 스페이스로.
_RE_MULTISPACE = re.compile(r"[ \t 　]+")

# 3개 이상의 마침표(... 또는 ....)를 말줄임표 하나(…)로 정규화.
_RE_ELLIPSIS = re.compile(r"\.{3,}")

# 같은 종결부호(? ! …)의 반복을 1개로 축약(예: "???" -> "?", "!!!" -> "!").
_RE_REPEAT_QMARK = re.compile(r"\?{2,}")
_RE_REPEAT_BANG = re.compile(r"!{2,}")
_RE_REPEAT_ELLIPSIS = re.compile(r"…{2,}")

# 종결부호(.,?!…) 앞의 불필요한 공백 제거 (예: "안녕 ." -> "안녕.").
_RE_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([.,?!…])")

# 쉼표/마침표 뒤에 공백이 없고 다음이 비공백/비부호면 공백 1개 삽입
# (예: "네,그래" -> "네, 그래"). 숫자 사이(소수점·천단위)는 건드리지 않는다.
_RE_SPACE_AFTER_COMMA = re.compile(r"(?<=[,])(?=[^\s\d.,?!…])")

# ASCII 영숫자/언더스코어 경계 판정용(글로서리 단어 경계 치환).
_RE_ASCII_WORDCHAR = re.compile(r"[0-9A-Za-z_]")


# --------------------------------------------------------------------------- #
# 공개 API
# --------------------------------------------------------------------------- #


def correct(
    transcript: Transcript,
    glossary: dict[str, str] | None = None,
    *,
    light_rules: bool = True,
) -> Transcript:
    """전사 결과의 텍스트를 교정한다(글로서리 치환 + 선택적 경량 규칙).

    타임스탬프와 세그먼트/단어 구조를 보존한 채 텍스트만 수정한 **새** :class:`Transcript`
    를 반환한다(입력은 변경하지 않는다). ARCHITECTURE §4 계약 시그니처를 그대로 구현한다.

    적용 순서(세그먼트별):
        1. 글로서리 강제 치환(긴 키 우선, 부분 겹침 방지) — 세그먼트 텍스트와 각 ``Word.text``.
        2. ``light_rules`` 가 참이면 경량 한국어 정리(공백/문장부호) — 세그먼트 텍스트만.

    Args:
        transcript: 전사 단계 산출 :class:`Transcript`. 변경되지 않는다.
        glossary: ``{원표기: 교정표기}`` 매핑. ``None`` 또는 빈 dict면 치환을 건너뛴다.
            ASCII 토큰(영문/숫자)은 단어 경계를 지켜 치환하고, 한글 등 비ASCII 키는
            부분 문자열로 치환한다(한국어는 토큰 경계 표시가 없으므로).
        light_rules: 경량 규칙 교정 적용 여부. 기본 ``True``. ``False`` 면 글로서리만 적용.

    Returns:
        텍스트가 교정된 새 :class:`Transcript`. ``language`` / ``duration`` 및 모든
        타임스탬프, 세그먼트 개수·순서, 단어 타임스탬프는 입력과 동일하다.
    """
    new_segments: list[Segment] = [
        _correct_segment(seg, glossary, light_rules=light_rules)
        for seg in transcript.segments
    ]
    return replace(transcript, segments=new_segments)


def correct_text(text: str, glossary: dict[str, str] | None = None) -> str:
    """단일 텍스트 조각에 글로서리 치환 + 경량 규칙을 적용한다(편의 함수).

    :func:`correct` 가 세그먼트 텍스트에 적용하는 것과 동일한 변환을 한 문자열에 대해
    수행한다. CLI/앱의 인라인 편집 미리보기나 단위 테스트에 쓸 수 있다.

    Args:
        text: 교정할 원본 텍스트.
        glossary: ``{원표기: 교정표기}`` 매핑. ``None`` 이면 글로서리 단계를 건너뛴다.

    Returns:
        글로서리 치환 후 경량 규칙으로 정리된 텍스트.
    """
    substituted = apply_glossary(text, glossary)
    return _apply_light_rules(substituted)


def apply_glossary(text: str, glossary: dict[str, str] | None) -> str:
    """글로서리 매핑을 텍스트에 결정적으로 적용한다.

    동일 입력에 대해 dict 순회 순서와 무관하게 같은 결과를 내도록, 키를 **길이 내림차순**
    (동률 시 사전순)으로 정렬해 적용한다. 이로써 짧은 키가 긴 키의 부분을 먼저 치환해
    버리는 비결정성을 막는다.

    치환 규칙:
        - 키가 ASCII 영숫자/언더스코어로만 이루어지면 **단어 경계**(앞뒤가 영숫자가 아닌
          위치)에서만 치환한다(예: ``"AI"`` 가 ``"BRAIN"`` 의 일부를 바꾸지 않도록).
        - 그 외(한글 포함 비ASCII 키)는 부분 문자열로 치환한다. 한국어는 단어 경계
          표시가 없고 조사가 붙으므로 부분 치환이 자연스럽다.
        - 빈 문자열 키는 무시한다.

    Args:
        text: 원본 텍스트.
        glossary: ``{원표기: 교정표기}`` 매핑. ``None``/빈 dict면 ``text`` 를 그대로 반환.

    Returns:
        치환이 적용된 텍스트.
    """
    if not glossary:
        return text

    for src, dst in _sorted_glossary_items(glossary):
        if not src:
            continue
        if _is_ascii_token(src):
            # 단어 경계 치환: \b 는 비ASCII 인접 시 한국어에서 예측이 어려워
            # 직접 lookaround 로 ASCII 단어문자 경계만 본다.
            pattern = re.compile(
                r"(?<![0-9A-Za-z_])" + re.escape(src) + r"(?![0-9A-Za-z_])"
            )
            text = pattern.sub(lambda _m, _d=dst: _d, text)
        else:
            text = text.replace(src, dst)
    return text


# --------------------------------------------------------------------------- #
# 내부 헬퍼
# --------------------------------------------------------------------------- #


def _correct_segment(
    seg: Segment,
    glossary: dict[str, str] | None,
    *,
    light_rules: bool,
) -> Segment:
    """세그먼트 하나를 교정한다(타임스탬프/구조 보존, 새 객체 반환)."""
    # 1) 단어 텍스트: 글로서리만 적용(공백/문장부호 정리는 단어 정렬을 깨므로 미적용).
    new_words: list[Word] = [
        replace(w, text=apply_glossary(w.text, glossary)) for w in seg.words
    ]

    # 2) 세그먼트 텍스트: 글로서리 → 경량 규칙.
    new_text = apply_glossary(seg.text, glossary)
    if light_rules:
        new_text = _apply_light_rules(new_text)

    return replace(seg, text=new_text, words=new_words)


def _apply_light_rules(text: str) -> str:
    """경량 한국어 정리 규칙을 적용한다(공백·문장부호 정규화).

    텍스트 길이를 줄일 수 있으나 토큰 타임스탬프와 무관한 세그먼트 텍스트 레벨에서만
    호출된다. 안전한(되돌릴 필요 없는) 정규화만 수행한다:

        - 말줄임표 정규화: ``...`` (3+) → ``…`` , ``…`` 반복 → 1개.
        - 종결부호 반복 축약: ``???`` → ``?`` , ``!!!`` → ``!`` .
        - 종결부호 앞 공백 제거, 쉼표 뒤 공백 보정.
        - 연속 공백/탭 → 단일 스페이스, 양끝 공백 제거.
    """
    # 말줄임표/반복 부호 정규화는 공백 정리보다 먼저 한다.
    text = _RE_ELLIPSIS.sub("…", text)
    text = _RE_REPEAT_ELLIPSIS.sub("…", text)
    text = _RE_REPEAT_QMARK.sub("?", text)
    text = _RE_REPEAT_BANG.sub("!", text)

    # 종결부호 앞 공백 제거 → 쉼표 뒤 공백 보정.
    text = _RE_SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _RE_SPACE_AFTER_COMMA.sub(" ", text)

    # 연속 공백 축약 후 양끝 트림.
    text = _RE_MULTISPACE.sub(" ", text)
    return text.strip()


def _sorted_glossary_items(glossary: dict[str, str]) -> list[tuple[str, str]]:
    """글로서리 항목을 결정적 순서(키 길이 내림차순, 동률 시 사전순)로 반환한다."""
    return sorted(glossary.items(), key=lambda kv: (-len(kv[0]), kv[0]))


def _is_ascii_token(key: str) -> bool:
    """키가 ASCII 영숫자/언더스코어로만 구성되면 True(단어 경계 치환 대상)."""
    return bool(key) and all(_RE_ASCII_WORDCHAR.match(ch) for ch in key)
