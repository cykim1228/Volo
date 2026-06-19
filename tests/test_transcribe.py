"""transcribe 단계 경계면 테스트 (faster-whisper 없이 — 가짜 모델 주입).

무거운 STT 추론은 실행하지 않고, 의존성 주입(`model=...`)으로 호출부를 검증한다:
- 한국어 품질/환각·반복 억제 파라미터가 실제로 `model.transcribe(...)` 로 전달되는가
- faster-whisper 산출물이 캐노니컬 `Transcript`/`Segment`/`Word` 로 정확히 변환되는가
- 파이프라인이 글로서리/프롬프트로 `initial_prompt` 를 구성하는가
"""

from __future__ import annotations

from volo_engine.models import TranscribeOptions
from volo_engine.transcribe import transcribe


class _FakeWord:
    def __init__(self, word, start, end, prob):
        self.word = word
        self.start = start
        self.end = end
        self.probability = prob


class _FakeSegment:
    def __init__(self, start, end, text, words):
        self.start = start
        self.end = end
        self.text = text
        self.words = words


class _FakeInfo:
    def __init__(self, language, duration):
        self.language = language
        self.duration = duration


class _FakeModel:
    """model.transcribe 호출 인자를 캡처하고 고정 결과를 돌려주는 가짜 모델."""

    def __init__(self):
        self.captured_kwargs = None

    def transcribe(self, wav_path, **kwargs):
        self.captured_kwargs = kwargs
        segments = [
            _FakeSegment(0.0, 1.5, "안녕하세요", [_FakeWord("안녕하세요", 0.0, 1.5, 0.95)]),
            _FakeSegment(1.6, 3.0, "반갑습니다", [_FakeWord("반갑습니다", 1.6, 3.0, 0.9)]),
        ]
        return iter(segments), _FakeInfo("ko", 3.0)


def _wav(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFF....WAVE")  # 내용은 무의미(모델을 주입하므로 실제 디코딩 없음)
    return str(p)


def test_quality_params_passed_to_model(tmp_path):
    """환각·반복 억제 + initial_prompt 파라미터가 model.transcribe 로 전달된다."""
    model = _FakeModel()
    opts = TranscribeOptions(initial_prompt="다음 용어가 등장합니다: GitHub.")
    transcribe(_wav(tmp_path), opts, model=model)

    kw = model.captured_kwargs
    assert kw["initial_prompt"] == "다음 용어가 등장합니다: GitHub."
    assert kw["condition_on_previous_text"] is False
    assert kw["temperature"] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert kw["compression_ratio_threshold"] == 2.4
    assert kw["log_prob_threshold"] == -1.0
    assert kw["no_speech_threshold"] == 0.6
    assert kw["hallucination_silence_threshold"] == 2.0
    assert kw["word_timestamps"] is True
    assert kw["vad_filter"] is True


def test_transcript_conversion(tmp_path):
    """faster-whisper 산출물이 Transcript/Segment/Word 로 정확히 변환된다."""
    tr = transcribe(_wav(tmp_path), TranscribeOptions(), model=_FakeModel())
    assert tr.language == "ko"
    assert tr.duration == 3.0
    assert len(tr.segments) == 2
    assert tr.segments[0].index == 0
    assert tr.segments[0].text == "안녕하세요"
    w = tr.segments[0].words[0]
    assert (w.text, w.start, w.end) == ("안녕하세요", 0.0, 1.5)
    assert 0.0 <= w.prob <= 1.0


def test_progress_monotonic(tmp_path):
    """진행률 콜백이 0→1 단조 증가하고 마지막에 1.0 을 보고한다."""
    seen: list[float] = []
    transcribe(_wav(tmp_path), TranscribeOptions(), model=_FakeModel(),
               progress_cb=lambda stage, r: seen.append(r))
    assert seen == sorted(seen)
    assert seen[-1] == 1.0


def test_pipeline_initial_prompt_from_glossary():
    """파이프라인이 글로서리 값 + 사용자 프롬프트로 initial_prompt 를 구성한다."""
    from volo_engine.pipeline import PipelineOptions, _build_initial_prompt, _build_transcribe_options

    opts = PipelineOptions(prompt="방송 인터뷰", glossary={"깃헙": "GitHub", "파이선": "파이썬"})
    prompt = _build_initial_prompt(opts)
    assert "방송 인터뷰" in prompt
    assert "GitHub" in prompt and "파이썬" in prompt

    topts = _build_transcribe_options(opts)
    assert topts.initial_prompt == prompt

    # 글로서리/프롬프트가 없으면 None
    assert _build_initial_prompt(PipelineOptions()) is None


def test_load_attempts_gpu_fallback(monkeypatch):
    """auto + GPU 감지 시 cuda/float16 → cuda/int8 → cpu/int8 폴백 순서."""
    import volo_engine.transcribe as T

    monkeypatch.setattr(T, "_cuda_available", lambda: True)
    attempts = T._load_attempts(TranscribeOptions(device="auto", compute_type="auto"))
    assert attempts == [("cuda", "float16"), ("cuda", "int8"), ("cpu", "int8")]


def test_load_attempts_cpu_only(monkeypatch):
    """GPU 미감지면 cpu/int8 단일 시도(폴백 불필요)."""
    import volo_engine.transcribe as T

    monkeypatch.setattr(T, "_cuda_available", lambda: False)
    assert T._load_attempts(TranscribeOptions(device="auto")) == [("cpu", "int8")]


def test_load_attempts_explicit_device_no_fallback(monkeypatch):
    """device 를 명시하면(=auto 아님) 폴백하지 않고 그 선택만 시도."""
    import volo_engine.transcribe as T

    monkeypatch.setattr(T, "_cuda_available", lambda: True)
    assert T._load_attempts(TranscribeOptions(device="cpu")) == [("cpu", "int8")]
    assert T._load_attempts(TranscribeOptions(device="cuda")) == [("cuda", "float16")]


def test_resolve_repo_id():
    """모델 크기 → repo id 해석(faster-whisper 설치 여부와 무관하게 안전)."""
    import volo_engine.transcribe as T

    assert T._resolve_repo_id("org/myrepo") == "org/myrepo"      # org/repo 는 그대로
    assert T._resolve_repo_id("nonexistent-size-xyz") is None    # 미상 → None
    # 알려진 크기는 매핑되거나(faster-whisper 설치 시) None(미설치) — 둘 다 허용
    assert T._resolve_repo_id("large-v3") in ("Systran/faster-whisper-large-v3", None)
