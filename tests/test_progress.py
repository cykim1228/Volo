"""worker.format_progress — 진행률 단계 → (라벨, 0~100%) 변환 테스트.

volo_app.worker 는 PySide6 미설치 환경에서도 import 가능(시그널은 더미 폴백). format_progress
/ overall_ratio 는 Qt 없이 동작하는 순수 로직이라 여기서 검증한다.
"""

from __future__ import annotations

from volo_app.worker import format_progress, overall_ratio


def test_download_stage_is_own_pass():
    """'download' 단계는 가중치 밖의 자체 0~100% 패스로 표시된다."""
    label, pct = format_progress("download", 0.42)
    assert "다운로드" in label
    assert pct == 42


def test_download_clamped():
    assert format_progress("download", 1.5)[1] == 100
    assert format_progress("download", -0.3)[1] == 0


def test_pipeline_stage_uses_weighted_ratio():
    """파이프라인 단계는 STAGE_WEIGHTS 누적 비율(overall_ratio)을 쓴다."""
    label, pct = format_progress("transcribe", 0.5)
    assert label == "전사 중"
    assert pct == int(round(overall_ratio("transcribe", 0.5) * 100))


def test_extract_stage_base():
    """오디오 추출 100% 는 전체에서 약 5%(extract 가중치)."""
    _, pct = format_progress("extract_audio", 1.0)
    assert pct == 5
