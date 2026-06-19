"""segment 단계 불변식 테스트(결정적·외부 의존 없음).

검증 대상(data-model 불변식 / PRD F3 수용 기준):
- I1 start < end
- I2 인접 cue 겹침 없음(next.start >= prev.end)
- I3 index 1부터 연속
- I4 줄 수 1~max_lines, 각 줄 길이 <= max_chars(단어 분할 불가 예외)
- I5 타임스탬프 >= 0, end <= duration
- CPS <= max_cps (가용 시간 확장으로 달성, 불가 시 리포트)
- 표시시간 min_duration ~ max_duration (보정 후, 가용 범위 내)
- 결정성(동일 입력 → 동일 출력)

import 은 stdlib + volo_engine.segment/models 만(conftest 헬퍼 사용).
"""

from __future__ import annotations

from conftest import (
    assert_subtitle_invariants,
    cps_of,
    make_segment,
    make_transcript,
    words_from_spec,
)

from volo_engine.models import SegmentRules
from volo_engine.segment import segment


# --------------------------------------------------------------------------- #
# 기본 불변식
# --------------------------------------------------------------------------- #


def test_empty_transcript_returns_empty():
    """세그먼트가 없으면 빈 리스트."""
    tr = make_transcript([], duration=0.0)
    assert segment(tr, SegmentRules()) == []


def test_blank_text_segment_returns_empty():
    """공백만 있는 세그먼트(단어 없음)는 cue 를 만들지 않는다."""
    seg = make_segment(0, 0.0, 1.0, "   ", words=[])
    tr = make_transcript([seg], duration=2.0)
    assert segment(tr, SegmentRules()) == []


def test_invariants_on_sample(sample_transcript, default_rules):
    """샘플 전사 → 불변식 I1~I5 모두 만족."""
    subs = segment(sample_transcript, default_rules)
    assert subs, "샘플은 최소 1개 cue 를 만들어야 함"
    assert_subtitle_invariants(subs, default_rules, sample_transcript.duration)


def test_index_is_one_based_and_contiguous(sample_transcript, default_rules):
    """I3: index 가 1,2,3… 으로 연속."""
    subs = segment(sample_transcript, default_rules)
    assert [s.index for s in subs] == list(range(1, len(subs) + 1))


def test_no_overlap_between_adjacent_cues(default_rules):
    """I2: 입력 단어가 시간상 붙어 있어도 출력 cue 는 겹치지 않는다."""
    # 일부러 빽빽하게 붙인 단어들(겹침 보정이 필요한 상황).
    words = words_from_spec(
        [
            ("문장하나입니다.", 0.0, 0.5),
            ("문장둘입니다.", 0.5, 1.0),
            ("문장셋입니다.", 1.0, 1.5),
            ("문장넷입니다.", 1.5, 2.0),
        ]
    )
    seg = make_segment(0, 0.0, 2.0, " ".join(w.text for w in words), words)
    tr = make_transcript([seg], duration=20.0)
    subs = segment(tr, default_rules)
    for a, b in zip(subs, subs[1:]):
        assert b.start >= a.end - 1e-6, f"겹침: {a.end} -> {b.start}"


# --------------------------------------------------------------------------- #
# CPS / 표시시간
# --------------------------------------------------------------------------- #


def test_cps_within_limit_when_time_available(default_rules):
    """AC3.2: 가용 시간이 충분하면 어떤 cue 도 max_cps 를 넘지 않는다.

    duration 을 크게 줘서(다음 cue 가 없거나 멀어서) end 확장이 가능하게 한다.
    """
    words = words_from_spec(
        [
            ("이것은", 0.0, 0.2),
            ("매우", 0.2, 0.35),
            ("빠르게", 0.35, 0.5),
            ("지나가는", 0.5, 0.7),
            ("자막입니다.", 0.7, 0.9),
        ]
    )
    seg = make_segment(0, 0.0, 0.9, " ".join(w.text for w in words), words)
    tr = make_transcript([seg], duration=30.0)
    subs = segment(tr, default_rules)
    for sub in subs:
        # 단일 어절 분할 불가로 인한 길이 예외는 없지만, CPS 는 시간확장으로 맞춰져야 함.
        assert cps_of(sub) <= default_rules.max_cps + 1e-6, (
            f"CPS 초과: {cps_of(sub):.2f} > {default_rules.max_cps} (cue={sub.lines})"
        )


def test_min_duration_enforced_when_room(default_rules):
    """AC3.3: 가용 공간이 있으면 표시시간이 min_duration 이상으로 보충된다."""
    words = words_from_spec([("짧음.", 0.0, 0.1)])
    seg = make_segment(0, 0.0, 0.1, "짧음.", words)
    tr = make_transcript([seg], duration=30.0)
    subs = segment(tr, default_rules)
    assert len(subs) == 1
    dur = subs[0].end - subs[0].start
    assert dur >= default_rules.min_duration - 1e-6, (
        f"min_duration 미달: {dur} < {default_rules.min_duration}"
    )


def test_max_duration_respected(default_rules):
    """누적 표시시간이 max_duration 을 넘으면 cue 가 분할된다."""
    # 한 단어씩 1초 간격으로 길게 — 한 cue 가 max_duration(7s)을 넘지 않아야 한다.
    spec = [(f"단어{i}", float(i), float(i) + 0.4) for i in range(12)]
    words = words_from_spec(spec)
    seg = make_segment(0, 0.0, 12.0, " ".join(w.text for w in words), words)
    tr = make_transcript([seg], duration=60.0)
    subs = segment(tr, default_rules)
    for sub in subs:
        assert (sub.end - sub.start) <= default_rules.max_duration + 1.0, (
            f"표시시간 과다: {sub.end - sub.start}"
        )


# --------------------------------------------------------------------------- #
# 줄 배분 / 줄 길이
# --------------------------------------------------------------------------- #


def test_line_length_within_max_chars(default_rules):
    """I4: 각 줄이 max_chars_per_line 을 넘지 않는다(어절 경계 분할 가능 시)."""
    spec = [
        ("가나다", 0.0, 0.4),
        ("라마바", 0.4, 0.8),
        ("사아자", 0.8, 1.2),
        ("차카타", 1.2, 1.6),
        ("파하가", 1.6, 2.0),
        ("나다라", 2.0, 2.4),
    ]
    words = words_from_spec(spec)
    seg = make_segment(0, 0.0, 2.4, " ".join(w.text for w in words), words)
    tr = make_transcript([seg], duration=30.0)
    subs = segment(tr, default_rules)
    for sub in subs:
        for line in sub.lines:
            if len(line) > default_rules.max_chars_per_line:
                assert " " not in line.strip(), f"분할 가능한데 긴 줄: {line!r}"


def test_at_most_max_lines(sample_transcript):
    """I4: 줄 수가 max_lines 를 넘지 않는다(다양한 max_lines)."""
    for max_lines in (1, 2):
        rules = SegmentRules(max_lines=max_lines)
        subs = segment(sample_transcript, rules)
        for sub in subs:
            assert len(sub.lines) <= max_lines


def test_max_chars_one_line_packs_into_single_line():
    """max_lines=1 이면 모든 cue 가 한 줄."""
    rules = SegmentRules(max_chars_per_line=100, max_lines=1)
    words = words_from_spec([("하나", 0.0, 0.5), ("둘", 0.5, 1.0), ("셋", 1.0, 1.5)])
    seg = make_segment(0, 0.0, 1.5, "하나 둘 셋", words)
    tr = make_transcript([seg], duration=10.0)
    subs = segment(tr, rules)
    for sub in subs:
        assert len(sub.lines) == 1


# --------------------------------------------------------------------------- #
# 분할 규칙(문장부호 / 글자수 예산)
# --------------------------------------------------------------------------- #


def test_sentence_boundary_splits_cue(default_rules):
    """문장부호로 끝나는 토큰 뒤에서 cue 가 끊긴다."""
    words = words_from_spec(
        [
            ("첫째문장.", 0.0, 0.8),
            ("둘째문장.", 2.0, 2.8),
        ]
    )
    seg = make_segment(0, 0.0, 2.8, "첫째문장. 둘째문장.", words)
    tr = make_transcript([seg], duration=10.0)
    subs = segment(tr, default_rules)
    assert len(subs) == 2, f"문장 경계 분할 실패: {[s.lines for s in subs]}"


def test_char_budget_splits_long_run(default_rules):
    """누적 글자수 > max_chars*max_lines 이면 분할된다(문장부호 없이)."""
    # 종결부호 없이 긴 어절열 → 글자수 예산으로 분할되어야 함.
    spec = [(f"어절{i}", i * 0.3, i * 0.3 + 0.25) for i in range(20)]
    words = words_from_spec(spec)
    seg = make_segment(0, 0.0, 6.0, " ".join(w.text for w in words), words)
    tr = make_transcript([seg], duration=60.0)
    rules = SegmentRules(max_chars_per_line=10, max_lines=2)  # budget=20
    subs = segment(tr, rules)
    assert len(subs) >= 2, "글자수 예산 초과인데 단일 cue"
    for sub in subs:
        total = sum(len(line.replace(" ", "")) for line in sub.lines)
        # 표시 글자수(공백 제외)는 대략 budget 이하(어절 경계 단위라 약간의 여유 허용).
        assert total <= rules.max_chars_per_line * rules.max_lines + 5


# --------------------------------------------------------------------------- #
# 폴백(word 없는 segment)
# --------------------------------------------------------------------------- #


def test_segment_without_words_fallback(default_rules):
    """word 타임스탬프가 없으면 segment 전체를 한 토큰으로 폴백한다."""
    seg = make_segment(0, 0.0, 3.0, "단어 타임스탬프 없는 세그먼트입니다.", words=[])
    tr = make_transcript([seg], duration=10.0)
    subs = segment(tr, default_rules)
    assert subs, "폴백 경로에서도 cue 생성"
    assert_subtitle_invariants(subs, default_rules, tr.duration)


def test_out_of_order_segments_sorted(default_rules):
    """전사 순서가 어긋나도 시간순으로 정렬되어 처리된다."""
    w1 = words_from_spec([("나중문장.", 5.0, 5.8)])
    w2 = words_from_spec([("먼저문장.", 0.0, 0.8)])
    seg_a = make_segment(0, 5.0, 5.8, "나중문장.", w1)
    seg_b = make_segment(1, 0.0, 0.8, "먼저문장.", w2)
    tr = make_transcript([seg_a, seg_b], duration=10.0)
    subs = segment(tr, default_rules)
    assert subs[0].start <= subs[-1].start
    # 첫 cue 가 시간상 먼저인 "먼저문장." 이어야 함.
    assert "먼저문장." in " ".join(subs[0].lines)


# --------------------------------------------------------------------------- #
# 결정성
# --------------------------------------------------------------------------- #


def test_determinism(sample_transcript, default_rules):
    """AC3.5: 동일 입력 → 동일 출력(재실행 일치)."""
    a = segment(sample_transcript, default_rules)
    b = segment(sample_transcript, default_rules)
    assert [(s.index, s.start, s.end, s.lines) for s in a] == [
        (s.index, s.start, s.end, s.lines) for s in b
    ]


def test_timestamps_clamped_to_duration():
    """I5: duration 을 넘는 단어 타임스탬프는 duration 으로 클램프된다."""
    words = words_from_spec([("끝단어", 9.0, 99.0)])  # end 가 duration 초과
    seg = make_segment(0, 9.0, 99.0, "끝단어", words)
    tr = make_transcript([seg], duration=10.0)
    rules = SegmentRules()
    subs = segment(tr, rules)
    assert subs
    for sub in subs:
        assert sub.end <= tr.duration + 1e-6, f"end>duration: {sub.end}"
