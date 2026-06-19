# 02 · architect 산출 요약 — 모듈 경계 & 함수 시그니처 계약

> architect 중간 산출물. 권위 문서: `docs/ARCHITECTURE.md`, 데이터 모델: `volo_engine/models.py`
> (기준 `.claude/skills/volo-architecture/references/data-model.md`). engine-dev/app-dev/qa 전달용 요약.

## 산출 파일 (모두 실제 Write 완료)
- `docs/ARCHITECTURE.md` — 스택·근거·모듈 경계·파이프라인 계약·디렉토리·패키징·UI 스택 결정.
- `volo_engine/models.py` — 캐노니컬 데이터 모델(dataclass, 타입힌트, docstring).
- `volo_engine/config.py` — 경로/상수/기본 옵션 팩토리.
- `volo_engine/errors.py` — VoloError 계열 공용 예외.
- `volo_engine/__init__.py` — 얕음(`__version__`만, 무거운 import 금지).
- `volo_cli/__init__.py`, `volo_app/__init__.py` — 패키지 마커.
- `pyproject.toml`, `requirements.txt`, `.gitignore`, `README.md` — 스캐폴드.

## 모듈 경계 (단방향 의존: cli/app → engine, 역방향 없음)
- `volo_engine` = UI 무관 순수 코어. UI를 절대 import 하지 않음.
- 결정적·stdlib 전용 모듈: `models`, `config`, `errors`, `segment`, `export`, `correct`, `style`.
- 무거운 의존성은 **함수 내부 import**: `audio`(ffmpeg/imageio-ffmpeg), `transcribe`(faster-whisper), `pipeline`.
- **얕은 `__init__` 계약(검증됨):** 무거운 의존성 미설치 상태에서도
  `from volo_engine import models, config, errors`, `from volo_engine.segment import segment`,
  `from volo_engine.export import export` 가능. (실측: faster_whisper/imageio_ffmpeg 미로딩 확인.)

## 데이터 모델 (volo_engine/models.py — 단일 진실 원천)
- 자료형: `Word`, `Segment`, `Transcript`, `Subtitle`, `StylePreset`, `TranscribeOptions`, `SegmentRules`.
- 타임스탬프 = 초 단위 `float`(SRT/VTT 변환 시에만 포맷). 언어코드 ISO-639-1. UTF-8. nullability `| None`.
- 불변식 I1~I5(QA 검증): start<end / 겹침금지 / index 1부터 연속 / lines 1~2줄·줄길이≤max_chars / ts≥0·end≤duration.

## 함수 시그니처 계약 (engine-dev 구현 대상)
```python
# audio.py
extract_audio(video_path: str, *, sample_rate=16000, channels=1, tmp_dir: str|None=None) -> str

# transcribe.py
transcribe(wav_path: str, opts: TranscribeOptions, *, model: object|None=None,
           progress_cb: ProgressCB|None=None) -> Transcript
load_model(opts: TranscribeOptions) -> object   # faster_whisper.WhisperModel

# correct.py  (결정적)
correct(transcript: Transcript, glossary: dict[str,str]|None=None, *, light_rules=True) -> Transcript

# segment.py  (결정적, 외부 의존 없음)
segment(transcript: Transcript, rules: SegmentRules) -> list[Subtitle]

# translate.py  (P3, 백엔드 교체형)
translate(subtitles: list[Subtitle], target_lang: str, *,
          backend: TranslateBackend|None=None, rules: SegmentRules|None=None) -> list[Subtitle]
# 백엔드 인터페이스: translate_lines(lines: list[str], src: str, tgt: str) -> list[str]

# style.py  (P2)
apply_style(subtitles: list[Subtitle], preset: StylePreset) -> list[Subtitle]
load_preset(name: str) -> StylePreset
write_style_sidecar(preset: StylePreset, out_path: str) -> str   # name.style.json

# export.py  (결정적)
export(subtitles: list[Subtitle], fmt: str, out_path: str, *,
       lang: str|None=None, bom: bool=False, newline: str="\n") -> str   # fmt in {'srt','vtt'}

# pipeline.py  (오케스트레이션)
run(video_path: str, *, transcribe_options: TranscribeOptions|None=None,
    segment_rules: SegmentRules|None=None, glossary: dict[str,str]|None=None,
    target_langs: list[str]|None=None, style_preset: StylePreset|None=None,
    out_path: str|None=None, fmt: str="srt", model: object|None=None,
    progress_cb: ProgressCB|None=None) -> PipelineResult
```
보조 타입(pipeline.py 내부, models.py 아님):
```python
ProgressCB = Callable[[str, float], None]   # (stage, fraction 0.0~1.0)
@dataclass
class PipelineResult:
    subtitles: list[Subtitle]; output_paths: list[str]
    transcript: Transcript; language: str; duration: float
```

## CLI 인자 계약 (app-dev — volo_cli.__main__:main)
`volo <input> --out <path> [--model --lang --device --max-cps --max-chars --glossary <json> --format srt|vtt]`
- 진행률 표준출력. 종료코드: 성공 0 / 실패 비0 + `VoloError.user_message()`(스택트레이스 비노출).

## UI 스택 결정
**PySide6 데스크톱(확정).** 엔진과 단일 언어·동일 프로세스 함수 호출(IPC 불필요), QThread 워커 + progress_cb→시그널,
PyInstaller .exe onedir. 대안(Electron/Tauri=Python 사이드카 IPC 복잡, 웹=오프라인/대용량 부적합) 미채택.

## OPEN QUESTION 처리 (planner/qa 확인 필요)
- OQ1 UI=PySide6 확정. OQ2 교정=MVP 글로서리+경량규칙(오프라인), LLM은 P2 가정.
- OQ3 번역=인터페이스만 확정(P3). OQ4 SRT 기본 `\n`/BOM 없음(qa 프리미어 실측). OQ5 모델 비동봉·런타임 다운로드 권고.

## 통지
- engine-dev: §4 시그니처 그대로 구현. 결정적 모듈 stdlib만, 무거운 의존성 함수 내부 import.
- app-dev: CLI 인자/ UI 연결 패턴(ARCHITECTURE §6). 엔진 호출만, list[Subtitle] 유지.
- qa: 불변식 I1~I5 + 보존성/결정성 + OQ4 실측.
