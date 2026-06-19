"""audio.build_audio_filters — ffmpeg 오디오 전처리 필터 체인 구성 테스트(순수, ffmpeg 불필요)."""

from __future__ import annotations

from volo_engine.audio import build_audio_filters


def test_both_on_denoise_before_normalize():
    f = build_audio_filters(denoise=True, normalize=True)
    assert "highpass=f=80" in f
    assert "afftdn" in f
    assert "loudnorm" in f
    # denoise(afftdn)가 normalize(loudnorm)보다 앞에 와야 한다.
    assert f.index("afftdn") < f.index("loudnorm")


def test_denoise_only():
    f = build_audio_filters(denoise=True, normalize=False)
    assert "afftdn" in f and "highpass" in f
    assert "loudnorm" not in f


def test_normalize_only():
    f = build_audio_filters(denoise=False, normalize=True)
    assert "loudnorm" in f
    assert "highpass" not in f and "afftdn" not in f


def test_both_off_is_empty():
    assert build_audio_filters(denoise=False, normalize=False) == ""
