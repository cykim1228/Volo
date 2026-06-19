"""transcribe — faster-whisper 기반 전사(STT) 단계.

WAV(16kHz mono PCM 권장) → :class:`~volo_engine.models.Transcript`.

이 모듈은 ``.claude/skills/volo-engine-dev/references/subtitle-domain.md`` §2 와
``docs/ARCHITECTURE.md`` §4 의 계약을 구현한다.

얕은 ``__init__`` 정책 준수
---------------------------
무거운 의존성 ``faster_whisper`` 는 **함수 내부에서 지연 import** 한다(top-level import 금지).
따라서 이 모듈을 import 하는 것만으로는 faster-whisper 설치를 강제하지 않으며,
모델을 주입(``model=...``)하면 faster-whisper 미설치 환경에서도 호출부를 검증할 수 있다.

device/compute_type ``"auto"`` 해석
-----------------------------------
``opts.device == "auto"`` 면 CUDA 가용 시 ``device="cuda", compute_type="float16"``,
아니면 ``device="cpu", compute_type="int8"`` 로 폴백한다(GPU 없는 머신에서도 완주).
``opts.compute_type`` 가 ``"auto"`` 가 아니면 사용자가 준 값을 존중한다.

진행률
------
faster-whisper 의 ``segments`` 는 **지연 평가 제너레이터**다. 이를 순회하며
``info.duration`` 대비 각 세그먼트의 ``end`` 로 0.0~1.0 단조 증가 비율을 산출해
``progress_cb("transcribe", ratio)`` 로 보고한다.
"""

from __future__ import annotations

from typing import Callable

from .errors import VoloInputError, VoloModelError, VoloTranscribeError
from .models import Segment, TranscribeOptions, Transcript, Word

__all__ = ["transcribe", "load_model", "resolve_device"]

# (stage_name, fraction 0.0~1.0) — pipeline 의 ProgressCB 계약과 동일 형태.
# pipeline.py 에 캐노니컬 정의가 있으나, 그 모듈에 대한 import 의존을 만들지 않기 위해
# 여기서는 동일 시그니처의 로컬 별칭을 둔다.
ProgressCB = Callable[[str, float], None]

# 진행률 보고 시 사용하는 단계 이름.
_STAGE = "transcribe"


def resolve_device(opts: TranscribeOptions) -> tuple[str, str]:
    """``opts`` 의 device/compute_type 를 faster-whisper 가 받는 구체값으로 해석한다.

    ``device="auto"`` 는 CUDA 가용성에 따라 ``"cuda"``/``"cpu"`` 로 확정하고,
    ``compute_type="auto"`` 는 확정된 device 에 맞춰(GPU=``float16``, CPU=``int8``) 정한다.
    사용자가 명시한 비-auto 값은 그대로 존중한다.

    CUDA 감지는 ``ctranslate2.get_cuda_device_count()`` 를 우선 사용하고(가벼움),
    실패하면 CUDA 없음(=CPU)으로 안전하게 폴백한다. 조용한 예외 무시는 device 판정에
    한정되며, 실제 모델 로드 실패는 :func:`load_model` 에서 별도로 보고한다.

    Args:
        opts: 전사 옵션. ``device`` / ``compute_type`` 를 참조한다.

    Returns:
        ``(device, compute_type)`` 튜플. 예: ``("cuda", "float16")`` / ``("cpu", "int8")``.

    Raises:
        VoloInputError: ``device`` 가 ``"auto"|"cuda"|"cpu"`` 가 아닐 때.
    """
    device = opts.device
    if device not in ("auto", "cuda", "cpu"):
        raise VoloInputError(
            f"지원하지 않는 device 값입니다: {device!r}",
            hint='device 는 "auto" | "cuda" | "cpu" 중 하나여야 합니다.',
        )

    if device == "auto":
        device = "cuda" if _cuda_available() else "cpu"

    compute_type = opts.compute_type
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"

    return device, compute_type


def _cuda_available() -> bool:
    """CUDA 디바이스 가용 여부를 추정한다(지연 import, 실패 시 False).

    ``ctranslate2`` 는 faster-whisper 의 백엔드라 함께 설치되며, GPU 카운트 조회가
    가볍다. import/조회 실패는 곧 CUDA 사용 불가로 간주해 CPU 로 폴백한다.
    """
    try:
        import ctranslate2  # type: ignore[import-not-found]

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _load_attempts(opts: TranscribeOptions) -> list[tuple[str, str]]:
    """모델 로드 시도 순서 ``[(device, compute_type), …]`` 를 만든다.

    ``device="auto"`` 로 GPU(cuda/float16)가 선택됐는데 GPU가 float16/CUDA를 제대로
    지원하지 않을 수 있다(예: 구형 GPU, 불완전한 CUDA 백엔드). 그 경우 단계적으로
    폴백한다: ``cuda/float16 → cuda/int8 → cpu/int8``. 이로써 어떤 머신에서도 완주한다
    (수용기준 AC2.3). 사용자가 device 를 명시(cuda/cpu)하면 그 선택을 존중해 폴백하지 않는다.

    Args:
        opts: 전사 옵션.

    Returns:
        시도할 ``(device, compute_type)`` 리스트(앞에서부터 순서대로 시도).
    """
    device, compute_type = resolve_device(opts)
    attempts: list[tuple[str, str]] = [(device, compute_type)]
    if opts.device == "auto" and device == "cuda":
        for fallback in (("cuda", "int8"), ("cpu", "int8")):
            if fallback not in attempts:
                attempts.append(fallback)
    return attempts


def load_model(opts: TranscribeOptions) -> object:
    """faster-whisper ``WhisperModel`` 을 로드한다(device/compute_type auto 해석 + 폴백).

    무거운 의존성(``faster_whisper``)은 이 함수 내부에서만 import 한다. 모델 가중치는
    최초 1회 자동 다운로드되어 캐시(:func:`volo_engine.config.model_cache_dir`)된다.
    ``device="auto"`` 에서 GPU 로드가 실패하면 :func:`_load_attempts` 순서대로 폴백한다
    (다운로드된 가중치는 캐시되므로 폴백 시 재다운로드하지 않는다).

    Args:
        opts: 전사 옵션. ``model_size`` / ``device`` / ``compute_type`` 를 사용한다.

    Returns:
        로드된 ``faster_whisper.WhisperModel`` 인스턴스(타입은 의도적으로 ``object``).

    Raises:
        VoloModelError: faster-whisper 미설치, 또는 모든 폴백 시도가 실패한 경우.
        VoloInputError: device 옵션 값이 잘못된 경우(:func:`resolve_device` 경유).
    """
    try:
        from faster_whisper import WhisperModel  # 지연 import
    except ImportError as exc:
        raise VoloModelError(
            "faster-whisper 가 설치되어 있지 않습니다.",
            hint="pip install faster-whisper 로 STT 백엔드를 설치하세요.",
        ) from exc

    # 모델 캐시 경로(VOLO_MODEL_CACHE/HF_HOME) 연결 — 최초 다운로드 위치를 일관되게.
    from .config import model_cache_dir

    cache_root = str(model_cache_dir())
    attempts = _load_attempts(opts)
    last_exc: Exception | None = None

    for dev, ctype in attempts:
        try:
            return WhisperModel(
                opts.model_size,
                device=dev,
                compute_type=ctype,
                download_root=cache_root,
            )
        except Exception as exc:  # GPU/compute 미지원 등 — 다음 후보로 폴백.
            last_exc = exc
            continue

    tried = ", ".join(f"{d}/{c}" for d, c in attempts)
    raise VoloModelError(
        f"STT 모델 로딩에 실패했습니다(model={opts.model_size!r}, 시도: {tried}): {last_exc}",
        hint=(
            "네트워크(최초 다운로드)·캐시 경로(VOLO_MODEL_CACHE/HF_HOME)·"
            "디바이스(CUDA 드라이버)를 확인하세요. GPU 문제가 계속되면 디바이스를 "
            "'cpu' 로 지정해 재시도하세요."
        ),
    ) from last_exc


# --------------------------------------------------------------------------- #
# 모델 다운로드 진행률 + 사전 준비
# --------------------------------------------------------------------------- #

_DOWNLOAD_STAGE = "download"  # progress_cb 단계 이름(모델 가중치 다운로드).


def _resolve_repo_id(model_size: str) -> str | None:
    """모델 크기 → huggingface repo id. 로컬 경로/미상이면 ``None``(다운로드 스킵).

    ``faster_whisper.utils._MODELS`` 의 공식 매핑(예: ``large-v3`` →
    ``Systran/faster-whisper-large-v3``)을 사용하고, ``org/repo`` 형태면 그대로 쓴다.
    """
    import os

    if os.path.isdir(model_size):
        return None
    try:
        from faster_whisper.utils import _MODELS

        if model_size in _MODELS:
            return _MODELS[model_size]
    except Exception:
        pass
    return model_size if "/" in model_size else None


def _download_tqdm(progress_cb: ProgressCB) -> type:
    """huggingface_hub 다운로드의 바이트 진행률을 ``progress_cb('download', ratio)`` 로
    보고하는 tqdm 서브클래스를 만든다. 바이트 단위(unit=='B') tqdm만 보고한다(파일 개수
    tqdm 등은 무시)."""
    from huggingface_hub.utils import tqdm as _BaseTqdm

    class _DownloadTqdm(_BaseTqdm):  # type: ignore[misc, valid-type]
        def update(self, n: int = 1) -> Any:  # type: ignore[override]
            ret = super().update(n)
            try:
                total = getattr(self, "total", None)
                if total and getattr(self, "unit", "") == "B":
                    progress_cb(_DOWNLOAD_STAGE, min(float(self.n) / float(total), 1.0))
            except Exception:
                pass
            return ret

    return _DownloadTqdm


def _ensure_downloaded(opts: TranscribeOptions, progress_cb: ProgressCB | None) -> None:
    """모델 가중치가 캐시에 없으면 진행률을 보고하며 미리 다운로드한다(best-effort).

    이미 캐시돼 있으면 ``snapshot_download`` 가 즉시 반환(진행률 이벤트 없음). 진행률 콜백이
    없으면(헤드리스/테스트) 아무것도 하지 않는다. 실패(네트워크/HF API 차이)해도 조용히
    통과한다 — 실제 로딩(:func:`load_model`)에서 정식 오류 처리·재시도가 이뤄진다.
    캐시 위치는 :func:`load_model` 의 ``download_root`` 와 동일(``model_cache_dir``)하다.
    """
    if progress_cb is None:
        return
    repo = _resolve_repo_id(opts.model_size)
    if repo is None:
        return
    try:
        from huggingface_hub import snapshot_download

        from .config import model_cache_dir

        snapshot_download(
            repo,
            cache_dir=str(model_cache_dir()),
            tqdm_class=_download_tqdm(progress_cb),
        )
        progress_cb(_DOWNLOAD_STAGE, 1.0)
    except Exception:
        pass


def prepare_model(opts: TranscribeOptions, *, progress_cb: ProgressCB | None = None) -> object:
    """모델을 준비한다: (필요 시) 진행률과 함께 다운로드 → 로드(디바이스 폴백 포함).

    파이프라인이 전사 전에 호출해 '모델 다운로드 중' 진행률을 노출하고, 로드된 모델을
    :func:`transcribe` 에 주입해 재로드를 피한다.

    Args:
        opts: 전사 옵션.
        progress_cb: 진행률 콜백(다운로드 단계는 ``stage="download"``).

    Returns:
        로드된 ``WhisperModel`` 인스턴스.
    """
    _ensure_downloaded(opts, progress_cb)
    return load_model(opts)


def transcribe(
    wav_path: str,
    opts: TranscribeOptions,
    *,
    model: object | None = None,
    progress_cb: ProgressCB | None = None,
) -> Transcript:
    """WAV 오디오를 전사해 :class:`Transcript` 를 만든다(faster-whisper).

    ``model`` 을 주입하면 그 모델을 그대로 사용하고(테스트/재사용), 주입하지 않으면
    :func:`load_model` 로 새로 로드한다. ``word_timestamps`` / ``vad_filter`` 는
    ``opts`` 값을 따른다(기본 둘 다 활성 — 세그멘테이션 정밀도·타임스탬프 안정화).

    faster-whisper 의 ``segments`` 는 지연 평가 제너레이터이므로, 순회하면서
    ``info.duration`` 대비 세그먼트 ``end`` 로 진행률을 계산해 ``progress_cb`` 로 보고한다.
    각 세그먼트의 ``words`` 를 :class:`Word` 로, 세그먼트를 :class:`Segment` 로 변환한다.

    Args:
        wav_path: 입력 WAV(16kHz mono PCM 권장) 경로.
        opts: 전사 옵션(:class:`TranscribeOptions`).
        model: 주입할 ``WhisperModel`` 인스턴스. ``None`` 이면 내부에서 로드한다.
        progress_cb: ``(stage, ratio)`` 진행률 콜백. ``stage="transcribe"``,
            ``ratio`` 는 0.0~1.0 단조 증가. ``None`` 이면 보고하지 않는다.

    Returns:
        전사 결과 :class:`Transcript` (``language`` / ``duration`` / ``segments``).
        ``segments`` 는 전사 순서대로 ``index`` 0 부터 부여된다.

    Raises:
        VoloInputError: ``wav_path`` 가 존재하지 않거나 옵션 값이 잘못된 경우.
        VoloModelError: 모델 로딩 실패(:func:`load_model` 경유).
        VoloTranscribeError: 전사 추론 중 실패.
    """
    from pathlib import Path

    if not Path(wav_path).is_file():
        raise VoloInputError(
            f"전사할 오디오 파일을 찾을 수 없습니다: {wav_path}",
            hint="extract_audio 가 생성한 WAV 경로가 올바른지 확인하세요.",
        )

    if model is None:
        model = load_model(opts)

    # faster-whisper transcribe 호출. segments 는 제너레이터(지연 평가).
    # 한국어 품질/환각·반복 억제 파라미터를 함께 전달한다(subtitle-domain §2).
    try:
        segments_gen, info = model.transcribe(  # type: ignore[attr-defined]
            wav_path,
            language=opts.language,
            word_timestamps=opts.word_timestamps,
            vad_filter=opts.vad_filter,
            beam_size=opts.beam_size,
            initial_prompt=opts.initial_prompt,
            condition_on_previous_text=opts.condition_on_previous_text,
            temperature=list(opts.temperature),
            compression_ratio_threshold=opts.compression_ratio_threshold,
            log_prob_threshold=opts.log_prob_threshold,
            no_speech_threshold=opts.no_speech_threshold,
            hallucination_silence_threshold=opts.hallucination_silence_threshold,
        )
    except Exception as exc:
        raise VoloTranscribeError(
            f"전사에 실패했습니다: {exc}",
            hint="입력 WAV 포맷(16kHz mono PCM)·모델 상태를 확인하세요.",
        ) from exc

    # info.duration: 전체 길이(초). 진행률 분모. 누락/0 이면 진행률 보고를 생략한다.
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    # 감지/지정 언어. info.language 우선, 없으면 옵션 언어, 그것도 없으면 빈 문자열.
    language = getattr(info, "language", None) or opts.language or ""

    out_segments: list[Segment] = []
    last_ratio = 0.0

    try:
        for index, seg in enumerate(segments_gen):
            words = _convert_words(getattr(seg, "words", None))
            out_segments.append(
                Segment(
                    index=index,
                    start=float(seg.start),
                    end=float(seg.end),
                    text=seg.text,
                    words=words,
                    speaker=None,
                    lang=language or "ko",
                )
            )

            if progress_cb is not None and duration > 0.0:
                # 단조 증가 보장: 직전 보고 비율보다 작아지지 않게 max 로 클램프.
                ratio = min(float(seg.end) / duration, 1.0)
                if ratio > last_ratio:
                    last_ratio = ratio
                    progress_cb(_STAGE, ratio)
    except VoloTranscribeError:
        raise
    except Exception as exc:
        raise VoloTranscribeError(
            f"전사 결과를 처리하는 중 실패했습니다: {exc}",
        ) from exc

    # 전사 완료 — 마지막에 1.0 을 한 번 보고(짧은 무음 꼬리로 last_ratio<1.0 일 수 있음).
    if progress_cb is not None and last_ratio < 1.0:
        progress_cb(_STAGE, 1.0)

    # info.duration 이 비었으면 마지막 세그먼트 end 로 보완(Transcript.duration 불변식용).
    if duration <= 0.0 and out_segments:
        duration = out_segments[-1].end

    return Transcript(
        language=language or "ko",
        duration=duration,
        segments=out_segments,
    )


def _convert_words(raw_words: object) -> list[Word]:
    """faster-whisper 세그먼트의 ``words`` 를 :class:`Word` 리스트로 변환한다.

    ``word_timestamps=False`` 이거나 단어 정보가 없으면 빈 리스트를 반환한다.
    faster-whisper 의 단어 객체는 ``word`` / ``start`` / ``end`` / ``probability`` 속성을 가진다.

    Args:
        raw_words: 세그먼트의 ``words`` (이터러블) 또는 ``None``.

    Returns:
        :class:`Word` 리스트(없으면 빈 리스트).
    """
    if not raw_words:
        return []

    words: list[Word] = []
    for w in raw_words:  # type: ignore[union-attr]
        words.append(
            Word(
                text=getattr(w, "word", ""),
                start=float(getattr(w, "start", 0.0) or 0.0),
                end=float(getattr(w, "end", 0.0) or 0.0),
                prob=float(getattr(w, "probability", 0.0) or 0.0),
            )
        )
    return words
