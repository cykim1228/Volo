"""volo — Volo 커맨드라인 진입점.

영상 한 개를 받아 :func:`volo_engine.pipeline.run` 으로 자막(SRT/VTT)을 생성한다.
이 모듈은 **엔진을 호출만** 한다 — 자체 자막 로직(전사/세그멘테이션/내보내기)을 두지 않는다.

사용 예::

    volo input.mp4 -o ./out --model large-v3 --lang ko --formats srt,vtt \\
        --translate en --preset default --glossary glossary.json

진행률은 콘솔에 단계별로 출력하고, 엔진의 :class:`~volo_engine.errors.VoloError` 는
사용자 친화적 메시지(스택트레이스 비노출)로 변환한다.

번역 백엔드(모킹 금지)
----------------------
``--translate`` 는 실제 번역 백엔드 주입을 요구한다. CLI 는 기본 번역 백엔드를 동봉하지
않으므로(가짜 통과 금지), 백엔드가 구성되지 않은 상태로 ``--translate`` 를 쓰면 엔진이
"번역 백엔드 미구성" 오류를 명확히 알린다. 향후 백엔드 플러그인 연결 지점은
:func:`_resolve_translate_backend` 다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from volo_engine import __version__ as engine_version
from volo_engine.config import default_segment_rules
from volo_engine.errors import VoloError
from volo_engine.pipeline import PipelineOptions, run

# 진행률 출력에 쓸 단계 이름 → 한국어 라벨.
_STAGE_LABELS = {
    "extract_audio": "오디오 추출",
    "transcribe": "전사(STT)",
    "correct": "교정",
    "segment": "세그멘테이션",
    "translate": "번역",
    "style": "스타일",
    "export": "내보내기",
}


def build_parser() -> argparse.ArgumentParser:
    """CLI 인자 파서를 구성한다.

    Returns:
        구성된 :class:`argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        prog="volo",
        description=(
            "Volo — 영상에서 자막(SRT/VTT)을 자동 생성한다. "
            "로컬 faster-whisper STT(GPU 자동감지→CPU 폴백), 한국어 교정·글로서리, "
            "CPS/줄바꿈 최적화 세그멘테이션."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "video",
        help="입력 영상/오디오 파일 경로(mp4, mov, mkv, wav, mp3 등).",
    )
    parser.add_argument(
        "-o",
        "--out",
        dest="out_dir",
        default=None,
        help="출력 디렉토리. 미지정 시 입력 영상과 같은 디렉토리.",
    )
    parser.add_argument(
        "--stem",
        dest="out_stem",
        default=None,
        help="출력 파일 베이스 이름(확장자 제외). 미지정 시 입력 파일명.",
    )
    parser.add_argument(
        "--model",
        dest="model_size",
        default="large-v3",
        help="Whisper 모델 크기(medium | large-v3 등). 한국어 정확도는 large-v3 최상.",
    )
    parser.add_argument(
        "--lang",
        dest="language",
        default="ko",
        help="전사 언어 코드(ISO-639-1). 'auto' 면 자동감지.",
    )
    parser.add_argument(
        "--device",
        dest="device",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="추론 디바이스. auto 면 CUDA 가용 시 GPU, 아니면 CPU.",
    )
    parser.add_argument(
        "--no-denoise",
        dest="denoise",
        action="store_false",
        help="오디오 잡음 제거 비활성화(기본: 활성 — 잡음 많은 영상 인식률↑).",
    )
    parser.add_argument(
        "--no-normalize",
        dest="normalize",
        action="store_false",
        help="음량 정규화(loudnorm) 비활성화(기본: 활성 — 작은 음성 보정).",
    )
    parser.add_argument(
        "--formats",
        dest="formats",
        default="srt",
        help="내보낼 자막 포맷(쉼표 구분). 예: srt,vtt.",
    )
    parser.add_argument(
        "--translate",
        dest="translate_to",
        default=None,
        metavar="LANG",
        help="번역 대상 언어 코드(예: en). 지정 시 번역 백엔드가 필요하다.",
    )
    parser.add_argument(
        "--preset",
        dest="preset",
        default=None,
        help="스타일 프리셋 이름(예: default, youtube, interview). export 시 사이드카 출력.",
    )
    parser.add_argument(
        "--max-cps",
        dest="max_cps",
        type=float,
        default=None,
        metavar="CPS",
        help="초당 글자수(CPS) 상한. 미지정 시 기본 17.0(한국어 권장 ≤12~17).",
    )
    parser.add_argument(
        "--max-chars",
        dest="max_chars",
        type=int,
        default=None,
        metavar="N",
        help="자막 한 줄 최대 글자수. 미지정 시 기본 20(한국어 권장 16~20).",
    )
    parser.add_argument(
        "--glossary",
        dest="glossary",
        default=None,
        metavar="FILE",
        help='글로서리 JSON 파일 경로({"원표기": "교정표기", ...}).',
    )
    parser.add_argument(
        "--prompt",
        dest="prompt",
        default=None,
        metavar="TEXT",
        help="인식 힌트(initial_prompt). 고유명사·도메인 어휘를 넣으면 인식 정확도가 올라간다. "
        "글로서리와 자동 합쳐진다.",
    )
    parser.add_argument(
        "--bom",
        action="store_true",
        help="SRT/VTT 에 UTF-8 BOM 선행(일부 플레이어 호환용). 기본 비활성(프리미어 권장).",
    )
    parser.add_argument(
        "--crlf",
        action="store_true",
        help="줄 끝을 CRLF(\\r\\n)로 출력. 기본 LF(\\n).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="진행률 출력을 끈다(오류만 표시).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"volo {engine_version}",
    )
    return parser


def _load_glossary(path: str) -> dict[str, str]:
    """글로서리 JSON 파일을 ``{원표기: 교정표기}`` dict 로 로드한다.

    Args:
        path: 글로서리 JSON 파일 경로.

    Returns:
        문자열→문자열 매핑.

    Raises:
        VoloError: 파일을 읽을 수 없거나, JSON 이 잘못됐거나, 객체(문자열 매핑)가 아닌 경우.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise VoloError(
            f"글로서리 파일을 찾을 수 없습니다: {path}",
            hint="--glossary 경로가 올바른지 확인하세요.",
        ) from exc
    except OSError as exc:
        raise VoloError(
            f"글로서리 파일을 읽을 수 없습니다: {path}",
            hint=str(exc),
        ) from exc
    except json.JSONDecodeError as exc:
        raise VoloError(
            f"글로서리 JSON 형식이 올바르지 않습니다: {path}",
            hint=str(exc),
        ) from exc

    if not isinstance(data, dict):
        raise VoloError(
            f"글로서리는 JSON 객체여야 합니다: {path}",
            hint='형식: {"원표기": "교정표기", ...}',
        )
    glossary: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise VoloError(
                f"글로서리의 키/값은 모두 문자열이어야 합니다: {path}",
                hint=f"문제 항목: {key!r} -> {value!r}",
            )
        glossary[key] = value
    return glossary


def _resolve_translate_backend(translate_to: str | None) -> Any | None:
    """번역 백엔드를 결정한다(향후 플러그인 연결 지점).

    현재 CLI 는 기본 번역 백엔드를 동봉하지 않는다(모킹 금지 — 가짜 번역을 통과시키지
    않는다). ``--translate`` 가 지정되면 ``None`` 을 반환하고, 실제 번역은 엔진의
    :func:`volo_engine.translate.translate` 가 백엔드 미구성 오류로 명확히 알린다.

    백엔드 플러그인(LLM/사전 API 등)을 연결할 때 이 함수에서 구현 객체를 생성·반환한다.

    Args:
        translate_to: 번역 대상 언어 코드(없으면 ``None``).

    Returns:
        :class:`~volo_engine.translate.TranslateBackend` 구현 객체 또는 ``None``.
    """
    return None


def _make_progress_printer() -> Any:
    """단계별 진행률을 한 줄로 갱신 출력하는 콜백을 만든다.

    같은 단계는 캐리지 리턴(``\\r``)으로 같은 줄을 갱신하고, 단계가 바뀌면 줄을 넘긴다.
    transcribe 처럼 시간이 오래 걸리는 단계의 진행 바를 보여준다.

    Returns:
        ``(stage, ratio)`` 시그니처의 진행률 콜백.
    """
    state: dict[str, Any] = {"stage": None, "last_emit": 0.0}

    def progress_cb(stage: str, ratio: float) -> None:
        label = _STAGE_LABELS.get(stage, stage)
        ratio = max(0.0, min(1.0, ratio))
        now = time.monotonic()

        if state["stage"] != stage:
            # 이전 단계 줄 마무리(완료 표시) 후 새 단계 시작.
            if state["stage"] is not None:
                sys.stderr.write("\n")
            state["stage"] = stage
            state["last_emit"] = 0.0

        # 출력 빈도 제한: 진행이 충분히 늘었거나, 0/1 경계일 때만 갱신.
        if ratio in (0.0, 1.0) or (now - state["last_emit"]) >= 0.1:
            state["last_emit"] = now
            bar = _render_bar(ratio)
            sys.stderr.write(f"\r  [{label}] {bar} {ratio * 100:5.1f}%")
            sys.stderr.flush()

    return progress_cb


def _render_bar(ratio: float, width: int = 24) -> str:
    """0.0~1.0 비율을 텍스트 진행 바로 렌더링한다."""
    filled = int(round(ratio * width))
    return "#" * filled + "-" * (width - filled)


def _build_segment_rules(args: argparse.Namespace):
    """``--max-cps`` / ``--max-chars`` 인자로 :class:`SegmentRules` 를 구성한다.

    둘 다 미지정이면 ``None`` 을 반환해 엔진이 기본 규칙(``default_segment_rules``)을 쓰게 한다.
    하나라도 지정되면 기본 규칙에서 해당 필드만 덮어쓴다(나머지 가독성 기준은 유지).

    Args:
        args: argparse 네임스페이스(``max_cps`` / ``max_chars``).

    Returns:
        구성된 :class:`~volo_engine.models.SegmentRules` 또는 ``None``.

    Raises:
        VoloError: 값이 0 이하 등 비정상일 때.
    """
    if args.max_cps is None and args.max_chars is None:
        return None

    rules = default_segment_rules()
    if args.max_cps is not None:
        if args.max_cps <= 0:
            raise VoloError(
                f"--max-cps 는 0보다 커야 합니다: {args.max_cps}",
                hint="예: --max-cps 14",
            )
        rules.max_cps = args.max_cps
    if args.max_chars is not None:
        if args.max_chars <= 0:
            raise VoloError(
                f"--max-chars 는 0보다 커야 합니다: {args.max_chars}",
                hint="예: --max-chars 16",
            )
        rules.max_chars_per_line = args.max_chars
    return rules


def _options_from_args(args: argparse.Namespace) -> PipelineOptions:
    """파싱된 인자를 :class:`PipelineOptions` 로 변환한다.

    Args:
        args: ``argparse`` 네임스페이스.

    Returns:
        구성된 :class:`PipelineOptions`.

    Raises:
        VoloError: 글로서리 로드 실패 시(``_load_glossary`` 경유).
    """
    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    language: str | None = None if args.language.lower() == "auto" else args.language
    glossary = _load_glossary(args.glossary) if args.glossary else None
    rules = _build_segment_rules(args)

    return PipelineOptions(
        model_size=args.model_size,
        language=language,
        glossary=glossary,
        prompt=args.prompt,
        rules=rules,  # --max-cps/--max-chars 미지정 시 None → 엔진 기본 SegmentRules
        translate_to=args.translate_to,
        preset=args.preset,
        formats=formats or ["srt"],
        device=args.device,
        denoise=args.denoise,
        normalize=args.normalize,
        out_dir=args.out_dir,
        out_stem=args.out_stem,
        bom=args.bom,
        newline="\r\n" if args.crlf else "\n",
        translate_backend=_resolve_translate_backend(args.translate_to),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점.

    Args:
        argv: 인자 리스트(``None`` 이면 ``sys.argv[1:]``). 테스트 주입용.

    Returns:
        프로세스 종료 코드(0=성공, 1=엔진 오류, 2=인자 오류는 argparse 가 처리).
    """
    # 한국어 Windows 콘솔(기본 cp949)에서 '—'·한글 등 비-cp949 문자 출력 시 발생하는
    # UnicodeEncodeError 를 막는다(도움말/진행률/요약이 모두 한글). 출력 스트림을 UTF-8로 고정.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)
    quiet = bool(args.quiet)

    try:
        options = _options_from_args(args)
    except VoloError as exc:
        sys.stderr.write(f"\n오류: {exc.user_message()}\n")
        return 1

    progress_cb = None if quiet else _make_progress_printer()

    if not quiet:
        sys.stderr.write(f"입력: {args.video}\n")
        sys.stderr.write(
            f"모델={options.model_size} 언어={options.language or 'auto'} "
            f"디바이스={options.device} 포맷={','.join(options.formats)}"
        )
        if options.translate_to:
            sys.stderr.write(f" 번역→{options.translate_to}")
        if options.preset:
            sys.stderr.write(f" 프리셋={options.preset}")
        sys.stderr.write("\n")

    try:
        result = run(args.video, options, progress_cb=progress_cb)
    except VoloError as exc:
        if not quiet:
            sys.stderr.write("\n")
        sys.stderr.write(f"오류: {exc.user_message()}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n중단되었습니다.\n")
        return 1

    if not quiet:
        sys.stderr.write("\n")

    # CPS 상한 초과 cue 경고(AC3.2): 표시시간 확장 여유가 없어 가독 속도가 빠른 구간.
    cps_over = result.get("cps_over_count", 0)
    if cps_over:
        indices = result.get("cps_over_indices", [])
        preview = ", ".join(str(i) for i in indices[:10])
        more = " …" if len(indices) > 10 else ""
        sys.stderr.write(
            f"경고: {cps_over}개 cue가 CPS 상한을 초과합니다(읽기 속도 빠름). "
            f"표시시간 확장 여유가 없는 구간입니다 — cue #{preview}{more}\n"
        )

    # 결과 요약: 생성된 파일 경로들을 stdout 으로(파이프/스크립트 활용 가능).
    output_paths = result.get("output_paths", [])
    print(
        f"완료: cue {result.get('subtitle_count', 0)}개, "
        f"언어={result.get('language', '?')}, "
        f"길이={result.get('duration', 0.0):.1f}s"
    )
    for path in output_paths:
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
