"""Volo 세그멘테이션 단계 — Whisper 전사를 화면 표시용 자막 cue로 재구성.

이 모듈은 Volo 엔진의 **핵심 부가가치**다. faster-whisper 가 내보내는 문장 단위의
길고 들쭉날쭉한 :class:`~volo_engine.models.Segment` 를, 한국어 자막 가독성 기준
(CPS·줄 길이·표시시간·cue 간격)에 맞춘 :class:`~volo_engine.models.Subtitle` cue로
재구성한다.

설계 원칙
--------
- **순수 파이썬·결정적.** 외부 의존성(faster-whisper/ffmpeg 등)을 import 하지 않는다.
  동일 ``Transcript`` + ``SegmentRules`` 는 항상 동일한 ``list[Subtitle]`` 을 낸다.
  → pytest 로 불변식(data-model I1~I5)을 외부 의존 없이 검증할 수 있다.
- **단어 타임스탬프 우선.** 가능하면 ``Segment.words`` 시퀀스로부터 cue를 만들어 타이밍을
  정밀하게 잡는다. word 가 없는 segment 는 segment 자체를 한 단위로 폴백 처리한다.
- **models.py 타입만 사용.** 입력 :class:`Transcript`, 규칙 :class:`SegmentRules`,
  출력 :class:`list[Subtitle]`. 중간 표현도 임의 dict/튜플 대신 dataclass(`_Token`)로 둔다.

알고리즘은 ``.claude/skills/volo-engine-dev/references/subtitle-domain.md`` §4 를 따른다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Segment, SegmentRules, Subtitle, Transcript, Word

__all__ = ["segment", "cps_exceeding"]


# --------------------------------------------------------------------------- #
# 내부 상수
# --------------------------------------------------------------------------- #

# 문장 종결로 간주하는 문장부호(이 문자로 끝나는 토큰 뒤에서 cue 를 끊는다).
_SENTENCE_ENDINGS: tuple[str, ...] = (".", "?", "!", "…")

# 자연 분할점으로 간주할 단어 간 침묵 간격(초). 이 이상 벌어지면 cue 를 끊는다.
_SILENCE_SPLIT_GAP: float = 0.7

# 한 줄 끝에 홀로 남으면 안 되는 한국어 조사·의존 형태(고아 회피용).
# 다음 줄 첫 어절이 이들로 시작하면 줄바꿈 지점을 한 어절 당겨 본다.
_ORPHAN_PARTICLES: tuple[str, ...] = (
    "을",
    "를",
    "이",
    "가",
    "은",
    "는",
    "에",
    "에서",
    "에게",
    "의",
    "와",
    "과",
    "도",
    "만",
    "로",
    "으로",
    "보다",
    "처럼",
    "까지",
    "부터",
    "한테",
    "께",
    "라고",
    "고",
)

# 부동소수 비교 오차 허용치(타이밍 보정 시 동률 판정).
_EPS: float = 1e-6


# --------------------------------------------------------------------------- #
# 내부 표현
# --------------------------------------------------------------------------- #


@dataclass
class _Token:
    """세그멘테이션 누적의 최소 단위(타임스탬프를 가진 어절/단어).

    ``Word`` 를 그대로 쓰지 않고 정규화된(공백 제거) 텍스트를 들고 다닌다.
    word 타임스탬프가 없는 segment 는 segment 전체를 하나의 ``_Token`` 으로 폴백한다.

    Attributes:
        text: 공백이 정리된 단어/어절 텍스트(빈 문자열 아님).
        start: 시작 시각(초).
        end: 끝 시각(초). ``start <= end``.
    """

    text: str
    start: float
    end: float


# --------------------------------------------------------------------------- #
# 공개 API
# --------------------------------------------------------------------------- #


def segment(transcript: Transcript, rules: SegmentRules) -> list[Subtitle]:
    """전사 결과를 화면 표시용 자막 cue 리스트로 재구성한다.

    subtitle-domain.md §4 알고리즘:

        1. 단어 타임스탬프 기반 재구성(words 우선, 없으면 segment 폴백).
        2. 누적 → 분할: 글자수/표시시간 한도, 문장부호 경계, 큰 침묵 간격에서 끊는다.
        3. 줄 배분: cue 텍스트를 1~2줄로, 어절 경계·균형·조사 고아 회피.
        4. 타이밍 보정: 최소 표시시간 보충, CPS 초과 시 표시시간 확장, 인접 cue 겹침 제거.
        5. 인덱스 1부터 연속 재부여.

    Args:
        transcript: 전사 단계 산출물. ``segments`` 의 ``words`` 가 있으면 그 타임스탬프를
            우선 사용한다. ``duration`` 은 모든 cue ``end`` 의 상한이다.
        rules: 한국어 자막 가독성 규칙(줄 길이/줄 수/CPS/표시시간/cue 간격).

    Returns:
        data-model 불변식 I1~I5 를 만족하는 :class:`Subtitle` 리스트.

        - I1 ``start < end``
        - I2 인접 cue ``next.start >= prev.end`` (겹침 금지)
        - I3 ``index`` 1부터 연속
        - I4 ``lines`` 1~``max_lines`` 개, 각 줄 길이 ≤ ``max_chars_per_line``
          (단어 분할 불가 예외 허용)
        - I5 모든 타임스탬프 ≥ 0, ``end <= transcript.duration``

        cue 가 하나도 만들어지지 않으면 빈 리스트를 반환한다.
    """
    # 1) 모든 segment 를 시간순 토큰 시퀀스로 평탄화.
    tokens = _flatten_tokens(transcript.segments, transcript.duration)
    if not tokens:
        return []

    # 2) 누적 → 분할: 토큰을 cue 묶음(토큰 리스트)으로 나눈다.
    cue_groups = _split_into_cues(tokens, rules)

    # 3) 각 묶음을 Subtitle 로 변환(줄 배분 포함).
    subtitles: list[Subtitle] = []
    for group in cue_groups:
        lines = _wrap_lines(
            [tok.text for tok in group],
            max_chars_per_line=rules.max_chars_per_line,
            max_lines=rules.max_lines,
        )
        if not lines:
            continue
        subtitles.append(
            Subtitle(
                index=0,  # 5)에서 재부여
                start=group[0].start,
                end=group[-1].end,
                lines=lines,
                lang=transcript.language or "ko",
            )
        )

    if not subtitles:
        return []

    # 4) 타이밍 보정(겹침 제거 + 최소 표시시간 + CPS) 및 5) 인덱스 재부여.
    _fix_timing(subtitles, rules, duration=transcript.duration)
    for i, sub in enumerate(subtitles, start=1):
        sub.index = i

    return subtitles


def cps_exceeding(subtitles: list[Subtitle], rules: SegmentRules) -> list[Subtitle]:
    """``max_cps`` 를 초과하는 cue 목록을 반환한다(리포트용, 결과 비변형).

    세그멘테이션은 텍스트를 더 쪼개지 않고 **표시시간 확장**만으로 CPS 를 낮춘다. 따라서
    인접 cue 겹침 방지·``duration`` 상한 때문에 확장 여유가 없으면 CPS 가 ``max_cps`` 를
    넘을 수 있다(subtitle-domain §4, 수용기준 AC3.2의 "분할 불가 예외"). 이 함수는 그런 cue 를
    집계해 CLI/UI 가 사용자에게 "가독 속도 초과 N개"를 알릴 수 있게 한다.

    Args:
        subtitles: 세그멘테이션 결과(또는 이후 단계의 cue 리스트). 변경하지 않는다.
        rules: 세그멘테이션 규칙(``max_cps`` 사용).

    Returns:
        CPS 가 ``max_cps`` 를 초과하는 :class:`Subtitle` 리스트(입력 순서 유지).
        ``max_cps <= 0`` 이면 빈 리스트.
    """
    if rules.max_cps <= 0:
        return []
    over: list[Subtitle] = []
    for sub in subtitles:
        dur = sub.end - sub.start
        if dur <= 0:
            continue
        cps = _display_char_count(sub.lines) / dur
        if cps > rules.max_cps + _EPS:
            over.append(sub)
    return over


# --------------------------------------------------------------------------- #
# 1) 토큰 평탄화
# --------------------------------------------------------------------------- #


def _flatten_tokens(segments: list[Segment], duration: float) -> list[_Token]:
    """모든 segment 를 시간순 ``_Token`` 시퀀스로 평탄화한다.

    word 타임스탬프가 있으면 단어 단위로, 없으면 segment 전체를 한 토큰으로 폴백한다.
    빈 텍스트·역전된(또는 비정상) 타임스탬프는 정규화하고, 음수/duration 초과는 클램프한다.

    Args:
        segments: 원시 세그먼트 리스트(전사 순서).
        duration: 오디오 전체 길이(초). 토큰 end 의 상한.

    Returns:
        시작 시각 기준 정렬된 ``_Token`` 리스트(빈 텍스트 토큰 제외).
    """
    upper = duration if duration > 0 else None
    tokens: list[_Token] = []

    for seg in segments:
        if seg.words:
            for word in seg.words:
                tok = _token_from_word(word, upper)
                if tok is not None:
                    tokens.append(tok)
        else:
            tok = _token_from_segment(seg, upper)
            if tok is not None:
                tokens.append(tok)

    # 전사 순서가 어긋나도 시간순을 보장(결정적 정렬: start → end).
    tokens.sort(key=lambda t: (t.start, t.end))
    return tokens


def _token_from_word(word: Word, upper: float | None) -> _Token | None:
    """단어를 정규화된 ``_Token`` 으로 변환한다(빈 텍스트면 ``None``)."""
    text = word.text.strip()
    if not text:
        return None
    start, end = _normalize_span(word.start, word.end, upper)
    return _Token(text=text, start=start, end=end)


def _token_from_segment(seg: Segment, upper: float | None) -> _Token | None:
    """word 가 없는 segment 전체를 한 ``_Token`` 으로 폴백 변환한다."""
    text = " ".join(seg.text.split())
    if not text:
        return None
    start, end = _normalize_span(seg.start, seg.end, upper)
    return _Token(text=text, start=start, end=end)


def _normalize_span(
    start: float, end: float, upper: float | None
) -> tuple[float, float]:
    """타임스탬프를 ``[0, upper]`` 로 클램프하고 ``start <= end`` 를 보장한다.

    음수는 0 으로, ``upper`` 초과는 ``upper`` 로 클램프한다. 역전(start > end)이면
    교환한다. 클램프 후 동일 값이면 그대로 둔다(0 길이 토큰은 cue 변환·타이밍 보정에서
    end 가 늘어난다).
    """
    s = max(0.0, start)
    e = max(0.0, end)
    if s > e:
        s, e = e, s
    if upper is not None:
        s = min(s, upper)
        e = min(e, upper)
    return s, e


# --------------------------------------------------------------------------- #
# 2) 누적 → 분할
# --------------------------------------------------------------------------- #


def _split_into_cues(tokens: list[_Token], rules: SegmentRules) -> list[list[_Token]]:
    """토큰 시퀀스를 cue 단위(토큰 리스트)로 분할한다.

    누적하며 다음 중 하나라도 만족하면 현재 토큰까지를 한 cue 로 확정하고 끊는다:

        - 현재 토큰을 더하면 누적 글자수 > ``max_chars_per_line * max_lines``
          (단, 첫 토큰 하나는 한도를 넘더라도 무조건 포함 — 단어 분할 불가 예외).
        - 현재 토큰을 더하면 누적 표시시간 > ``max_duration``.
        - 현재 토큰이 문장부호로 끝남(종결 경계 → 토큰 포함 후 끊음).
        - 다음 토큰과의 침묵 간격이 ``_SILENCE_SPLIT_GAP`` 이상(자연 분할점 → 끊음).

    Args:
        tokens: 시간순 ``_Token`` 리스트(비어 있지 않음).
        rules: 세그멘테이션 규칙.

    Returns:
        cue 별 토큰 리스트의 리스트(각 원소는 비어 있지 않음).
    """
    char_budget = max(1, rules.max_chars_per_line * rules.max_lines)

    cues: list[list[_Token]] = []
    current: list[_Token] = []

    for i, tok in enumerate(tokens):
        if current:
            prospective_chars = _joined_char_count(current, tok)
            prospective_dur = tok.end - current[0].start
            if prospective_chars > char_budget or prospective_dur > rules.max_duration:
                # 한도 초과: 현재 토큰은 다음 cue 로 넘긴다(현재 cue 확정).
                cues.append(current)
                current = []

        current.append(tok)

        # 종결 경계: 문장부호로 끝나면 여기서 cue 를 확정.
        if _ends_sentence(tok.text):
            cues.append(current)
            current = []
            continue

        # 자연 분할점: 다음 토큰과 큰 침묵이면 확정.
        if i + 1 < len(tokens):
            gap = tokens[i + 1].start - tok.end
            if gap >= _SILENCE_SPLIT_GAP:
                cues.append(current)
                current = []

    if current:
        cues.append(current)

    return cues


def _joined_char_count(current: list[_Token], nxt: _Token) -> int:
    """현재 cue 토큰들에 다음 토큰을 더했을 때의 표시 글자수(어절 사이 공백 1 포함)."""
    count = sum(len(tok.text) for tok in current) + len(current) - 1  # 기존 공백
    count += 1 + len(nxt.text)  # 추가 공백 + 다음 토큰
    return count


def _ends_sentence(text: str) -> bool:
    """토큰 텍스트가 문장 종결 부호로 끝나는지 판정한다(따옴표·괄호 후행 허용)."""
    stripped = text.rstrip("\"'”’」』）)】]")
    return stripped.endswith(_SENTENCE_ENDINGS)


# --------------------------------------------------------------------------- #
# 3) 줄 배분
# --------------------------------------------------------------------------- #


def _wrap_lines(
    words: list[str], *, max_chars_per_line: int, max_lines: int
) -> list[str]:
    """어절 리스트를 1~``max_lines`` 줄로 배분한다.

    - 한 줄에 ``max_chars_per_line`` 이하가 되도록 어절(공백) 경계에서 자른다.
    - 두 줄이 되면 길이를 균형 있게(상단이 같거나 약간 길게) 나누고, 다음 줄 첫 어절이
      조사로 시작하는 고아를 피하도록 분할 지점을 조정한다.
    - ``max_lines`` 를 초과하는 분량이면(상위 분할 단계의 char_budget 보장으로 드묾)
      남는 어절을 마지막 줄에 이어 붙인다(단어 분할 불가 예외).

    Args:
        words: cue 의 어절 텍스트 리스트.
        max_chars_per_line: 한 줄 최대 글자수.
        max_lines: cue 최대 줄 수(≥ 1).

    Returns:
        줄 문자열 리스트(1~``max_lines`` 개, 빈 줄 없음). 입력이 비면 빈 리스트.
    """
    words = [w for w in words if w]
    if not words:
        return []

    lines_cap = max(1, max_lines)
    line_cap = max(1, max_chars_per_line)

    one_line = " ".join(words)
    # 단일 줄로 충분하거나(가장 읽기 쉬움), 줄 수 한도가 1이거나, 어절이 하나뿐이면 한 줄.
    if len(one_line) <= line_cap or lines_cap == 1 or len(words) == 1:
        return [one_line]

    # 두 줄(이상) 배분: 균형 분할점을 찾는다.
    return _wrap_two_lines(words, line_cap=line_cap, max_lines=lines_cap)


def _wrap_two_lines(
    words: list[str], *, line_cap: int, max_lines: int
) -> list[str]:
    """어절을 균형 잡힌 두 줄로 나눈다(고아 회피, 상단 우선).

    전체 길이의 절반에 가장 가까운 어절 경계를 분할점으로 삼되, 첫 줄이 ``line_cap`` 을
    넘지 않는 범위에서 고른다. 분할 직후 어절(둘째 줄 첫 어절)이 조사로 시작하면 분할점을
    한 칸 당겨 고아를 피한다. ``max_lines`` 가 3 이상이면 둘째 줄을 재귀로 더 나눈다.
    """
    total = len(" ".join(words))
    target = total / 2.0

    # 누적 길이(각 split 위치에서 첫 줄 글자수)를 계산.
    best_split = 1
    best_score = float("inf")
    for split in range(1, len(words)):
        first = " ".join(words[:split])
        first_len = len(first)
        # 첫 줄이 한도를 넘으면 이 분할점은 부적합(단, 모두 부적합하면 아래 폴백).
        over = first_len - line_cap
        # 점수: 균형 편차 + 한도 초과 페널티(초과는 강하게 회피).
        balance = abs(first_len - target)
        penalty = max(0, over) * 1000.0
        # 고아 회피: 둘째 줄 첫 어절이 조사로 시작하면 가점 페널티.
        orphan_penalty = 0.0
        if words[split].startswith(_ORPHAN_PARTICLES):
            orphan_penalty = 50.0
        score = balance + penalty + orphan_penalty
        if score < best_score - _EPS:
            best_score = score
            best_split = split

    first_words = words[:best_split]
    rest_words = words[best_split:]

    first_line = " ".join(first_words)
    if max_lines <= 2 or not rest_words:
        second_line = " ".join(rest_words)
        result = [first_line]
        if second_line:
            result.append(second_line)
        return result

    # max_lines >= 3: 나머지를 재귀로 더 분할.
    return [first_line, *_wrap_two_lines(
        rest_words, line_cap=line_cap, max_lines=max_lines - 1
    )]


# --------------------------------------------------------------------------- #
# 4) 타이밍 보정
# --------------------------------------------------------------------------- #


def _fix_timing(
    subtitles: list[Subtitle], rules: SegmentRules, *, duration: float
) -> None:
    """cue 타이밍을 in-place 보정해 불변식 I1·I2·I5 와 CPS/표시시간을 맞춘다.

    순서(결정적):
        1. 각 cue 의 ``start <= end`` 0 길이 방지(최소 양수 길이 확보).
        2. 겹침 제거: ``cur.start = max(cur.start, prev.end + min_gap)``.
           start 가 밀리면 end 도 함께 밀어 길이를 보존하되 duration 상한을 지킨다.
        3. 최소 표시시간 보충: ``duration < min_duration`` 이면 다음 cue 시작 −
           ``min_gap`` 까지(또는 ``duration`` 상한까지) end 를 늘린다.
        4. CPS 보정: ``cps > max_cps`` 이면 이상적 표시시간까지 end 를 늘린다(가용 범위 내).

    텍스트(줄 분할)는 건드리지 않는다 — 표시시간 확장만으로 CPS 를 낮춘다(길이상 분할은
    이미 §2 char_budget 에서 제한됨). 시간 확장 여유가 없으면 CPS 상한을 넘을 수 있으나,
    겹침·duration 상한 불변식이 우선한다.

    Args:
        subtitles: 인덱스 미부여 상태의 cue 리스트(시간순). in-place 수정.
        rules: 세그멘테이션 규칙.
        duration: 오디오 전체 길이(초). 모든 end 의 상한. 0 이하면 상한 미적용.
    """
    upper = duration if duration > 0 else None
    n = len(subtitles)

    # 0 길이 방지를 위한 아주 작은 양수(밀리초 단위).
    min_positive = 0.001

    for i, sub in enumerate(subtitles):
        # --- 1) start/end 클램프 + 0 길이 방지 ---
        sub.start = max(0.0, sub.start)
        sub.end = max(sub.end, sub.start)
        if upper is not None:
            sub.start = min(sub.start, upper)
            sub.end = min(sub.end, upper)

        # --- 2) 이전 cue 와 겹침 제거 ---
        if i > 0:
            prev = subtitles[i - 1]
            min_start = prev.end + rules.min_gap
            if sub.start < min_start:
                shift = min_start - sub.start
                sub.start = min_start
                sub.end += shift  # 길이 보존(아래에서 상한 클램프)
                if upper is not None:
                    sub.start = min(sub.start, upper)
                    sub.end = min(sub.end, upper)

        # 다음 cue 시작 한계(있으면): 최소 간격을 둔 지점까지만 확장 가능.
        next_limit: float | None = None
        if i + 1 < n:
            next_start_raw = max(subtitles[i + 1].start, 0.0)
            if upper is not None:
                next_start_raw = min(next_start_raw, upper)
            next_limit = next_start_raw - rules.min_gap

        # 확장 가능한 end 상한: duration 과 다음 cue 한계 중 작은 값.
        ceiling = _expansion_ceiling(sub.start, upper, next_limit)

        # --- 0 길이면 최소 양수 길이 확보(상한 내에서) ---
        if sub.end - sub.start < min_positive:
            sub.end = min(sub.start + min_positive, ceiling)
            # 상한이 start 와 거의 같아 확보 불가하면, 다음 cue 를 밀어내기보다
            # 최소 양수 길이를 강제(겹침은 다음 루프에서 다음 cue 의 start 보정으로 해소).
            if sub.end - sub.start < min_positive:
                sub.end = sub.start + min_positive

        # --- 3) 최소 표시시간 보충 ---
        if sub.end - sub.start < rules.min_duration:
            desired_end = sub.start + rules.min_duration
            sub.end = min(desired_end, ceiling) if ceiling > sub.end else sub.end

        # --- 4) CPS 보정(표시시간 확장) ---
        char_count = _display_char_count(sub.lines)
        cur_dur = sub.end - sub.start
        if rules.max_cps > 0 and cur_dur > 0:
            cps = char_count / cur_dur
            if cps > rules.max_cps + _EPS:
                ideal_dur = char_count / rules.max_cps
                desired_end = sub.start + ideal_dur
                if desired_end > sub.end:
                    sub.end = min(desired_end, ceiling) if ceiling > sub.end else sub.end

        # 최종 0 길이/역전 방지.
        if sub.end <= sub.start:
            sub.end = sub.start + min_positive
            if upper is not None and sub.end > upper:
                # duration 상한을 넘기느니 start 를 약간 당긴다. 단 이전 cue 와의 겹침(I2)은
                # duration 상한(I5)보다 우선하므로, 이전 cue end+min_gap 아래로는 당기지 않는다.
                # (일반적으로 도달하지 않는 극단 케이스 — 마지막 cue 가 정확히 duration 일 때.)
                floor = 0.0
                if i > 0:
                    floor = subtitles[i - 1].end + rules.min_gap
                sub.end = upper
                sub.start = max(floor, upper - min_positive)
                if sub.start > sub.end:
                    # floor 가 upper 를 넘으면 길이 확보가 불가능 — start=end 회피를 위해
                    # 아주 작게라도 end 를 floor 위로 둔다(I1 우선, duration 미세 초과 허용).
                    sub.start = floor
                    sub.end = floor + min_positive


def _expansion_ceiling(
    start: float, upper: float | None, next_limit: float | None
) -> float:
    """end 를 확장할 수 있는 상한을 계산한다.

    duration 상한(``upper``)과 다음 cue 와의 간격 한계(``next_limit``) 중 더 작은 값.
    어느 한계도 ``start`` 보다 작아지지 않도록 한다(최소 ``start`` 보장).
    """
    ceiling = float("inf")
    if upper is not None:
        ceiling = min(ceiling, upper)
    if next_limit is not None:
        ceiling = min(ceiling, next_limit)
    # 한계가 start 보다 앞서면 확장 불가 — start 를 바닥으로.
    return max(ceiling, start)


def _display_char_count(lines: list[str]) -> int:
    """CPS 계산용 표시 글자수(공백 제외, 줄 합산)를 센다."""
    return sum(len(line.replace(" ", "")) for line in lines)
