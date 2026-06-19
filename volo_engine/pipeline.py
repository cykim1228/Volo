"""파이프라인(pipeline) 단계 — 전체 자막 생성 오케스트레이션 + 진행률 콜백.

영상 한 개를 받아 다음 순서로 처리해 자막 파일(들)을 만든다::

    extract_audio → transcribe → correct → segment
        → (translate) → (apply_style) → export(각 fmt × 각 언어)

이 모듈은 ``docs/ARCHITECTURE.md`` §4 의 ``run(...)`` 계약을 구현하되, 호출 편의를 위해
모든 파라미터를 :class:`PipelineOptions` 한 자료형으로 묶어 받는다. 각 단계는
:mod:`volo_engine` 의 기존 모듈(``audio`` / ``transcribe`` / ``correct`` / ``segment`` /
``translate`` / ``style`` / ``export``)을 **그대로 호출만** 한다(엔진 내부 재구현 없음).

얕은(shallow) import 정책
--------------------------
무거운 의존성(``faster_whisper`` / ``ffmpeg`` / ``imageio_ffmpeg``)을 끌어오는
서브모듈(``audio`` / ``transcribe``)은 **함수 내부에서 지연 import** 한다. 따라서 이
모듈을 import 하는 것만으로는 무거운 의존성 설치를 강제하지 않으며, 결정적 단계만
사용하는 경로(예: 단위 테스트)는 가볍게 유지된다.

진행률 보고
----------
``progress_cb(stage, ratio)`` 는 단계 이름과 0.0~1.0 비율을 받는다.

- ``stage`` 는 ``"extract_audio" | "transcribe" | "correct" | "segment" |
  "translate" | "style" | "export"`` 중 하나.
- ``ratio`` 는 **해당 단계 내부**의 진행도(0.0~1.0)다. 단계 간 가중치는 호출자(UI/CLI)가
  단계 이름으로 판단한다. transcribe 단계는 내부 진행률을 그대로 흘려보낸다.

번역 백엔드(모킹 금지)
----------------------
``translate`` 는 실제 번역 백엔드 주입을 요구한다(:mod:`volo_engine.translate`).
``options.translate_to`` 를 지정하면서 ``options.translate_backend`` 를 주지 않으면
:class:`~volo_engine.translate.TranslateBackendNotConfiguredError` 가 그대로 전파된다
(가짜 통과·플레이스홀더 출력 금지).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import default_segment_rules, default_transcribe_options
from .errors import VoloInputError
from .models import SegmentRules, Subtitle, TranscribeOptions, Transcript

__all__ = ["PipelineOptions", "PipelineResult", "ProgressCB", "run"]

# (stage_name, fraction 0.0~1.0) — 단계별 진행률 콜백 계약.
ProgressCB = Callable[[str, float], None]

# 진행률/디스패치에 쓰는 단계 이름(고정 문자열).
_STAGE_EXTRACT = "extract_audio"
_STAGE_TRANSCRIBE = "transcribe"
_STAGE_CORRECT = "correct"
_STAGE_SEGMENT = "segment"
_STAGE_TRANSLATE = "translate"
_STAGE_STYLE = "style"
_STAGE_EXPORT = "export"


# --------------------------------------------------------------------------- #
# 옵션 / 결과 자료형
# --------------------------------------------------------------------------- #


@dataclass
class PipelineOptions:
    """파이프라인 실행 옵션(한 영상 처리에 필요한 모든 설정).

    엔진 데이터 모델(:class:`TranscribeOptions` / :class:`SegmentRules` /
    :class:`StylePreset`)을 직접 노출하지 않고, CLI/앱이 다루기 쉬운 평면(flat) 옵션으로
    받아 :func:`run` 내부에서 모델 자료형으로 변환한다.

    Attributes:
        model_size: Whisper 모델 크기(``"medium"`` | ``"large-v3"`` 등).
            기본 ``"large-v3"`` (한국어 정확도 최상).
        language: 전사 언어 코드(ISO-639-1). ``None`` 이면 자동감지. 기본 ``"ko"``.
        glossary: ``{원표기: 교정표기}`` 글로서리. ``None`` 이면 글로서리 치환 생략.
            (correct 단계의 경량 규칙 교정은 항상 적용.)
        rules: 세그멘테이션 규칙(:class:`SegmentRules`). ``None`` 이면
            :func:`volo_engine.config.default_segment_rules` 기본값 사용.
        translate_to: 번역 대상 언어 코드(ISO-639-1, 예: ``"en"``). ``None`` 이면 번역 생략.
            지정 시 ``translate_backend`` 가 반드시 있어야 한다(모킹 금지).
        preset: 적용할 스타일 프리셋 이름(예: ``"default"``). ``None`` 이면 스타일 미적용.
            export 시 ``<base>.style.json`` 사이드카가 함께 출력된다.
        formats: 내보낼 자막 포맷 리스트(예: ``["srt", "vtt"]``). 기본 ``["srt"]``.
        device: 추론 디바이스(``"auto"`` | ``"cuda"`` | ``"cpu"``). 기본 ``"auto"``.
        out_dir: 자막 파일을 쓸 출력 디렉토리. ``None`` 이면 입력 영상과 같은 디렉토리.
        out_stem: 출력 파일 베이스 이름(확장자 제외). ``None`` 이면 입력 영상 파일명.
        bom: SRT/VTT 에 UTF-8 BOM 선행 여부. 기본 ``False``(프리미어 권장).
        newline: 줄 끝 문자(``"\\n"`` | ``"\\r\\n"``). 기본 ``"\\n"``.
        translate_backend: 번역을 수행할 :class:`~volo_engine.translate.TranslateBackend`
            구현. ``translate_to`` 지정 시 필수. ``None`` 이면 번역 시 명확한 오류를 던진다.
    """

    model_size: str = "large-v3"
    language: str | None = "ko"
    glossary: dict[str, str] | None = None
    prompt: str | None = None  # 인식 힌트(initial_prompt). 글로서리와 합쳐 STT에 전달
    rules: SegmentRules | None = None
    translate_to: str | None = None
    preset: str | None = None
    formats: list[str] = field(default_factory=lambda: ["srt"])
    device: str = "auto"
    denoise: bool = True   # 오디오 잡음 제거(STT 정확도 향상)
    normalize: bool = True  # 음량 정규화(loudnorm)
    out_dir: str | None = None
    out_stem: str | None = None
    bom: bool = False
    newline: str = "\n"
    translate_backend: Any | None = None


@dataclass
class PipelineResult:
    """파이프라인 실행 결과.

    :func:`run` 은 (task 계약상) dict 를 반환하지만, 내부적으로 이 자료형을 만들어
    ``to_dict()`` 로 직렬화한다. 앱/CLI 는 dict 의 ``output_paths`` 만 보면 된다.

    Attributes:
        subtitles: 세그멘테이션(필요 시 번역/스타일 적용)된 자막 cue 리스트.
        output_paths: 생성된 모든 산출 파일 경로(자막 + 스타일 사이드카). 결정적 순서.
        outputs_by_format: ``{(fmt, lang): path}`` 매핑(lang 은 원본이면 ``None``).
        transcript: 교정 후 전사 결과(원문 보존·재활용용).
        language: 최종 확정 언어 코드.
        duration: 오디오 전체 길이(초).
        cps_over_indices: CPS 상한(``rules.max_cps``)을 초과한 cue 의 ``index`` 목록.
            표시시간 확장 여유가 없어 분할이 막힌 구간(AC3.2 리포트). 보통 빈 리스트.
    """

    subtitles: list[Subtitle]
    output_paths: list[str]
    outputs_by_format: dict[tuple[str, str | None], str]
    transcript: Transcript
    language: str
    duration: float
    cps_over_indices: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """task 계약용 dict 로 직렬화한다(출력 파일 경로들 중심)."""
        return {
            "output_paths": list(self.output_paths),
            "outputs_by_format": {
                f"{fmt}:{lang or 'src'}": path
                for (fmt, lang), path in self.outputs_by_format.items()
            },
            "language": self.language,
            "duration": self.duration,
            "subtitle_count": len(self.subtitles),
            "cps_over_count": len(self.cps_over_indices),
            "cps_over_indices": list(self.cps_over_indices),
        }


# --------------------------------------------------------------------------- #
# 공개 진입점
# --------------------------------------------------------------------------- #


def run(
    video_path: str,
    options: PipelineOptions,
    progress_cb: ProgressCB | None = None,
) -> dict[str, Any]:
    """영상 한 개에 대해 전체 자막 생성 파이프라인을 실행한다.

    순서: ``extract_audio → transcribe → correct → segment → (translate) →
    (apply_style) → export(각 fmt × 각 언어)``. 단계마다 ``progress_cb(stage, ratio)`` 로
    진행률을 보고하며, 임시 WAV 는 완료(성공/실패 무관) 시 정리한다.

    Args:
        video_path: 입력 영상/오디오 파일 경로.
        options: 실행 옵션(:class:`PipelineOptions`).
        progress_cb: ``(stage, ratio)`` 진행률 콜백. ``None`` 이면 보고하지 않는다.

    Returns:
        생성된 산출물 정보 dict. 핵심 키:

            - ``output_paths``: ``list[str]`` — 생성된 모든 파일 경로(자막 + 사이드카).
            - ``outputs_by_format``: ``{"srt:src": path, "srt:en": path, ...}``.
            - ``language`` / ``duration`` / ``subtitle_count``.

    Raises:
        VoloInputError: 입력 경로·포맷·옵션 값이 잘못된 경우.
        VoloDependencyError / VoloAudioError / VoloModelError / VoloTranscribeError /
        VoloExportError: 각 단계의 외부 의존/처리 실패(원본 예외 그대로 전파).
        TranslateBackendNotConfiguredError: ``translate_to`` 지정 + 백엔드 미주입 시.
    """
    if not isinstance(video_path, str) or not video_path:
        raise VoloInputError("입력 경로(video_path)가 비어 있습니다.")
    if not os.path.isfile(video_path):
        raise VoloInputError(
            f"입력 파일을 찾을 수 없습니다: {video_path}",
            hint="경로가 올바른지, 파일이 존재하는지 확인하세요.",
        )

    formats = _normalize_formats(options.formats)
    out_dir, out_stem = _resolve_output_base(video_path, options)

    # 결정적 모듈은 top-level import(가벼움). 무거운 단계는 함수 내부에서 지연 import.
    from . import correct as correct_mod
    from . import export as export_mod
    from . import segment as segment_mod

    transcribe_opts = _build_transcribe_options(options)
    segment_rules = options.rules if options.rules is not None else default_segment_rules()

    wav_path: str | None = None
    try:
        # --- 0) 모델 준비: 필요 시 다운로드(진행률 'download') → 로드(디바이스 폴백) ---- #
        # 무거운 첫-실행 다운로드를 맨 앞에서 진행률과 함께 처리한다(오디오 추출보다 먼저).
        from . import transcribe as transcribe_mod

        model = transcribe_mod.prepare_model(transcribe_opts, progress_cb=progress_cb)

        # --- 1) 오디오 추출 (ffmpeg; 지연 import) --------------------------- #
        _report(progress_cb, _STAGE_EXTRACT, 0.0)
        from . import audio as audio_mod

        wav_path = audio_mod.extract_audio(
            video_path,
            tmp_dir=out_dir,
            denoise=options.denoise,
            normalize=options.normalize,
        )
        _report(progress_cb, _STAGE_EXTRACT, 1.0)

        # --- 2) 전사 (사전 로드한 모델 주입 — 재로드/재다운로드 없음) ------- #
        transcript = transcribe_mod.transcribe(
            wav_path,
            transcribe_opts,
            model=model,
            progress_cb=progress_cb,  # transcribe 가 ("transcribe", ratio) 로 보고
        )

        # --- 3) 교정 (글로서리 + 경량 규칙; 결정적) ------------------------- #
        _report(progress_cb, _STAGE_CORRECT, 0.0)
        transcript = correct_mod.correct(transcript, options.glossary, light_rules=True)
        _report(progress_cb, _STAGE_CORRECT, 1.0)

        # --- 4) 세그멘테이션 (CPS/줄길이; 결정적·핵심 부가가치) ------------- #
        _report(progress_cb, _STAGE_SEGMENT, 0.0)
        subtitles = segment_mod.segment(transcript, segment_rules)
        _report(progress_cb, _STAGE_SEGMENT, 1.0)
    finally:
        # 임시 WAV 정리(성공/실패 무관). audio._cleanup 와 동일한 안전 삭제.
        if wav_path is not None:
            _cleanup_tmp(wav_path)

    # --- 5) 번역 (선택; 실제 백엔드 필요 — 모킹 금지) ----------------------- #
    if options.translate_to:
        from . import translate as translate_mod

        _report(progress_cb, _STAGE_TRANSLATE, 0.0)
        subtitles = translate_mod.translate(
            subtitles,
            options.translate_to,
            backend=options.translate_backend,
            rules=segment_rules,
        )
        _report(progress_cb, _STAGE_TRANSLATE, 1.0)

    # --- 6) 스타일 (선택) -------------------------------------------------- #
    preset = None
    if options.preset:
        from . import style as style_mod

        _report(progress_cb, _STAGE_STYLE, 0.0)
        preset = style_mod.load_preset(options.preset)
        subtitles = style_mod.apply_style(subtitles, preset)
        _report(progress_cb, _STAGE_STYLE, 1.0)

    # --- 7) 내보내기 (각 fmt × 각 언어) ------------------------------------ #
    output_paths, outputs_by_format = _export_all(
        export_mod,
        subtitles,
        formats=formats,
        out_dir=out_dir,
        out_stem=out_stem,
        translate_to=options.translate_to,
        preset=preset,
        bom=options.bom,
        newline=options.newline,
        progress_cb=progress_cb,
    )

    # CPS 상한 초과 cue 집계(리포트용, AC3.2). 텍스트/타이밍은 변경하지 않는다.
    cps_over_indices = [
        sub.index for sub in segment_mod.cps_exceeding(subtitles, segment_rules)
    ]

    result = PipelineResult(
        subtitles=subtitles,
        output_paths=output_paths,
        outputs_by_format=outputs_by_format,
        transcript=transcript,
        language=transcript.language,
        duration=transcript.duration,
        cps_over_indices=cps_over_indices,
    )
    return result.to_dict()


# --------------------------------------------------------------------------- #
# 내부 헬퍼
# --------------------------------------------------------------------------- #


def _build_transcribe_options(options: PipelineOptions) -> TranscribeOptions:
    """``PipelineOptions`` 의 STT 관련 필드로 :class:`TranscribeOptions` 를 만든다.

    기본값 팩토리에서 시작해 model_size / language / device 를 덮어쓰고, 글로서리·사용자
    프롬프트로 ``initial_prompt`` 를 구성한다. 단어 타임스탬프·VAD·환각/반복 억제 등 검증된
    기본은 유지한다.
    """
    opts = default_transcribe_options()
    opts.model_size = options.model_size
    opts.language = options.language
    opts.device = options.device
    opts.initial_prompt = _build_initial_prompt(options)
    return opts


def _build_initial_prompt(options: PipelineOptions) -> str | None:
    """인식 단계 힌트(``initial_prompt``)를 구성한다.

    사용자 ``prompt`` + 글로서리의 **올바른 표기(값)**를 합쳐, 고유명사·브랜드명·도메인 어휘를
    인식 단계에서부터 올바르게 잡도록 유도한다(사후 치환보다 효과적). Whisper 프롬프트는
    마지막 ~224 토큰만 쓰이므로 용어 수를 제한한다.

    Returns:
        구성된 프롬프트 문자열, 비면 ``None``.
    """
    parts: list[str] = []
    if options.prompt:
        parts.append(options.prompt.strip())

    if options.glossary:
        seen: set[str] = set()
        terms: list[str] = []
        for value in options.glossary.values():
            term = (value or "").strip()
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
            if len(terms) >= 50:  # 프롬프트 과대화 방지(토큰 한도)
                break
        if terms:
            parts.append("다음 용어가 등장합니다: " + ", ".join(terms) + ".")

    prompt = " ".join(p for p in parts if p).strip()
    return prompt or None


def _normalize_formats(formats: list[str] | None) -> list[str]:
    """포맷 리스트를 정규화한다(소문자화·공백제거·중복제거, 순서 보존).

    빈 입력이면 기본 ``["srt"]``. 검증(지원 포맷 여부)은 export 단계가 담당하므로
    여기서는 형태만 다듬는다.
    """
    if not formats:
        return ["srt"]
    seen: set[str] = set()
    out: list[str] = []
    for fmt in formats:
        norm = str(fmt).strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out or ["srt"]


def _resolve_output_base(
    video_path: str, options: PipelineOptions
) -> tuple[str, str]:
    """출력 디렉토리와 베이스 파일명(stem)을 결정한다.

    out_dir 미지정 시 입력 영상과 같은 디렉토리, out_stem 미지정 시 입력 파일명(확장자 제외).
    out_dir 가 없으면 생성한다.

    Returns:
        ``(out_dir, out_stem)`` 절대 경로 디렉토리와 stem.

    Raises:
        VoloInputError: out_dir 생성에 실패한 경우.
    """
    abs_video = os.path.abspath(video_path)
    out_dir = options.out_dir or os.path.dirname(abs_video)
    out_dir = os.path.abspath(out_dir)
    out_stem = options.out_stem or os.path.splitext(os.path.basename(abs_video))[0]

    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise VoloInputError(
            f"출력 디렉토리를 만들 수 없습니다: {out_dir}",
            hint=str(exc),
        ) from exc
    return out_dir, out_stem


def _export_all(
    export_mod: Any,
    subtitles: list[Subtitle],
    *,
    formats: list[str],
    out_dir: str,
    out_stem: str,
    translate_to: str | None,
    preset: Any | None,
    bom: bool,
    newline: str,
    progress_cb: ProgressCB | None,
) -> tuple[list[str], dict[tuple[str, str | None], str]]:
    """각 포맷 × 각 언어로 자막 파일을 내보내고 산출 경로를 모은다.

    - 원본 언어는 항상 내보낸다.
    - ``translate_to`` 가 있으면 언어별 분리 파일(``<stem>.<lang>.<fmt>``)도 내보낸다
      (subtitle-domain §6: 다국어 동시 출력 시 언어별 파일 분리).
    - 원본+번역이 함께면 원본도 ``<stem>.<srclang>.<fmt>`` 로 언어 접미사를 붙여 충돌·혼동을
      방지한다. 번역이 없으면 원본은 접미사 없이 ``<stem>.<fmt>``.
    - ``preset`` 이 있으면 스타일 사이드카(``<stem>.style.json``)를 한 번 출력한다.

    Returns:
        (생성 파일 경로 리스트, ``{(fmt, lang|None): path}`` 매핑).
    """
    _report(progress_cb, _STAGE_EXPORT, 0.0)

    src_lang = subtitles[0].lang if subtitles else "ko"

    # 출력 대상: (lang_for_export, suffix_lang) — lang_for_export 는 export(lang=...) 인자,
    # suffix_lang 은 파일명 접미사. 원본은 export lang=None.
    targets: list[tuple[str | None, str | None]] = []
    if translate_to:
        # 다국어: 원본/번역 모두 언어 접미사를 붙인다.
        targets.append((None, src_lang))
        targets.append((translate_to, translate_to))
    else:
        # 단일 언어(원본): 접미사 없이.
        targets.append((None, None))

    output_paths: list[str] = []
    outputs_by_format: dict[tuple[str, str | None], str] = {}

    total = max(1, len(formats) * len(targets))
    done = 0
    for fmt in formats:
        for export_lang, suffix_lang in targets:
            filename = (
                f"{out_stem}.{suffix_lang}.{fmt}" if suffix_lang else f"{out_stem}.{fmt}"
            )
            out_path = os.path.join(out_dir, filename)
            written = export_mod.export(
                subtitles,
                fmt,
                out_path,
                lang=export_lang,
                bom=bom,
                newline=newline,
            )
            output_paths.append(written)
            outputs_by_format[(fmt, export_lang)] = written
            done += 1
            _report(progress_cb, _STAGE_EXPORT, min(done / total, 1.0))

    # 스타일 사이드카: 첫 자막 파일 옆에 한 번만 출력(확장자만 .style.json 으로 교체).
    if preset is not None and output_paths:
        sidecar = export_mod.write_style_sidecar(preset, output_paths[0])
        output_paths.append(sidecar)

    _report(progress_cb, _STAGE_EXPORT, 1.0)
    return output_paths, outputs_by_format


def _report(progress_cb: ProgressCB | None, stage: str, ratio: float) -> None:
    """진행률 콜백을 안전하게 호출한다(콜백 예외는 파이프라인을 깨지 않음)."""
    if progress_cb is None:
        return
    try:
        progress_cb(stage, ratio)
    except Exception:
        # UI 콜백의 오류가 처리 파이프라인을 중단시키지 않도록 한다.
        pass


def _cleanup_tmp(path: str) -> None:
    """임시 WAV 파일을 조용히 제거한다(정리 실패는 무시)."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
