# Volo 아키텍처

> 단일 진실 원천: 데이터 모델은 `volo_engine/models.py`(기준 문서 `.claude/skills/volo-architecture/references/data-model.md`),
> 엔진 도메인 지식은 `.claude/skills/volo-engine-dev/references/subtitle-domain.md`.
> 입력: `docs/PRD.md`. 본 문서는 스택·모듈 경계·파이프라인 인터페이스·디렉토리·패키징·UI 스택 결정을 정의한다.
> 작성: architect · 2026-06-19.

---

## 1. 설계 목표와 불변 원칙

1. **엔진/UI 완전 분리.** `volo_engine` 은 UI를 import 하지 않는 순수 라이브러리다. CLI(`volo_cli`)와
   데스크톱 앱(`volo_app`)은 엔진을 **호출만** 한다. 이 경계가 향후 데스크톱→웹 UI 교체를 가능케 한다.
2. **데이터 모델 = 단일 진실 원천.** 모든 파이프라인 단계는 `volo_engine/models.py` 의 자료형
   (`Word`/`Segment`/`Transcript`/`Subtitle`/`StylePreset`/`TranscribeOptions`/`SegmentRules`)으로만
   통신한다. 타임스탬프는 **초 단위 float**, 언어 코드는 ISO-639-1, 텍스트는 UTF-8.
3. **파이프라인 = 교체 가능한 단계.** 각 단계는 명시적 입력/출력 타입을 가지며 생략·교체 가능하다.
4. **모킹 금지.** 임시 mock 통과 금지. 단, 결정적 검증을 위한 **의존성 주입**(예: `transcribe(..., model=...)`)은
   실제 호출 경로를 검증하는 수단이므로 허용한다.
5. **얕은 엔진 `__init__`.** `volo_engine/__init__` 은 무거운 의존성(`faster_whisper`/`ffmpeg`/`imageio_ffmpeg`)을
   top-level import 하지 않는다. → 결정적 모듈(`models`/`segment`/`export`)과 테스트는 무거운 의존성 없이 import 가능.

---

## 2. 기술 스택과 근거

| 영역 | 선택 | 근거 |
|------|------|------|
| 언어/런타임 | **Python 3.11+** | 단일 언어로 엔진+CLI+UI 통합. faster-whisper 생태계와 일치. `X | None` 타입 문법 사용. |
| STT | **faster-whisper (CTranslate2)** | 로컬 추론(API 비용 0, 영상 외부 업로드 없음), 단어 타임스탬프 지원, `large-v3` 한국어 정확도. |
| 오디오 추출 | **ffmpeg** (시스템 PATH 우선 → `imageio-ffmpeg` 번들 폴백) | 사실상 표준. 폴백으로 별도 설치 없이 동작 보장(PRD AC1.2). |
| 가속 | **CUDA(float16) 자동 감지 → CPU(int8) 폴백** | GPU 없는 머신에서도 예외 없이 완주(AC2.3). `device="auto"` 가 이 로직으로 해석. |
| UI(Phase 2) | **PySide6 데스크톱** | §6 결정 참조. |
| 자막 포맷 | **SRT(주력) / VTT** | 프리미어 캡션 트랙 직접 임포트. 내부는 float 초, export 시에만 타임코드 포맷. |
| 패키징 | **pyproject.toml 패키지 + `volo` CLI 엔트리 → PyInstaller onedir** | §7 참조. |
| 테스트 | **pytest** | 결정적 모듈(segment/export/correct) 불변식 검증. |
| 린트 | **ruff** | 빠른 단일 린터/포매터. |

런타임 의존성(핵심): `faster-whisper`, `imageio-ffmpeg`. UI 의존성(`PySide6`)은
`[project.optional-dependencies].app` 으로 분리해 엔진/CLI만 쓰는 환경을 가볍게 유지한다.

---

## 3. 모듈 경계

```
volo_engine/                 # UI 무관 코어 (단일 진실 원천)
├── __init__.py              # 얕음: __version__ 만. 무거운 import 금지.
├── models.py                # 캐노니컬 데이터 모델 (stdlib만)
├── config.py                # 기본 경로/상수/기본 옵션 팩토리 (stdlib만)
├── errors.py                # VoloError 계열 공용 예외 (stdlib만)
├── audio.py                 # extract_audio  [ffmpeg / imageio-ffmpeg]   (engine-dev)
├── transcribe.py            # transcribe     [faster-whisper]            (engine-dev)
├── correct.py               # correct (글로서리 치환 + 경량 규칙)        (engine-dev, stdlib)
├── segment.py               # segment (CPS/줄길이 세그멘테이션)          (engine-dev, stdlib·결정적)
├── translate.py             # translate (교체형 백엔드 인터페이스)        (engine-dev)
├── style.py                 # apply_style + 프리셋 로드/사이드카          (engine-dev, stdlib)
├── export.py                # export (SRT/VTT writer)                    (engine-dev, stdlib·결정적)
└── pipeline.py              # run(...) 오케스트레이션 + 진행률 콜백        (engine-dev)

volo_cli/                    # 커맨드라인 (엔진 호출만)
├── __init__.py
└── __main__.py              # main() — argparse, 진행률 출력, 에러→사용자 메시지  (app-dev)

volo_app/                    # 데스크톱 UI (PySide6, Phase 2; 엔진 호출만)
├── __init__.py
└── ...                      # main_window, worker(QThread), 위젯 등        (app-dev)

assets/presets/              # StylePreset JSON (default/youtube/interview), 글로서리 샘플
tests/                       # pytest (결정적 모듈 중심)
docs/                        # PRD.md, ARCHITECTURE.md
```

**의존성 방향(단방향):** `volo_cli` → `volo_engine` ← `volo_app`. 엔진은 어느 UI도 import 하지 않는다.

**모듈별 무거운 의존성 사용 위치(얕은 `__init__` 정책의 근거):**

| 모듈 | 무거운 import | 결정적/테스트 가능 |
|------|---------------|--------------------|
| `models`, `config`, `errors`, `segment`, `export`, `correct`, `style` | 없음(stdlib) | ✅ 의존성 없이 import·테스트 |
| `audio` | `imageio_ffmpeg`(폴백 시) + subprocess ffmpeg | 함수 내부에서만 import |
| `transcribe` | `faster_whisper.WhisperModel` | 함수/로더 내부에서만 import; 모델 주입으로 테스트 |
| `pipeline` | 위 모듈을 함수 내부에서 사용 | 진행률 콜백 계약은 단위 테스트 |

---

## 4. 파이프라인 인터페이스 (계약)

모든 시그니처는 `volo_engine/models.py` 자료형을 사용한다. engine-dev 는 아래 시그니처를 그대로 구현한다.

```python
# audio.py
def extract_audio(video_path: str, *, sample_rate: int = 16000,
                  channels: int = 1, tmp_dir: str | None = None) -> str:
    """영상/오디오 → 16kHz mono PCM WAV 경로. 임시 디렉토리에 생성.
    ffmpeg: 시스템 PATH 우선 → imageio_ffmpeg 폴백 → 둘 다 없으면 VoloDependencyError."""

# transcribe.py
def transcribe(wav_path: str, opts: TranscribeOptions,
               *, model: object | None = None,
               progress_cb: ProgressCB | None = None) -> Transcript:
    """WAV → Transcript. model 주입 시 그 모델 사용(테스트). device='auto' → CUDA/CPU 자동.
    progress_cb 로 0.0~1.0 단조 증가 진행률 보고(info.duration 기준)."""

def load_model(opts: TranscribeOptions) -> object:
    """faster_whisper.WhisperModel 로드(device/compute_type auto 해석). 실패 시 VoloModelError."""

# correct.py
def correct(transcript: Transcript, glossary: dict[str, str] | None = None,
            *, light_rules: bool = True) -> Transcript:
    """글로서리 강제 치환 + (선택) 경량 규칙 교정. 텍스트만 수정, 타임스탬프 보존."""

# segment.py  (결정적·외부 의존 없음)
def segment(transcript: Transcript, rules: SegmentRules) -> list[Subtitle]:
    """Transcript → list[Subtitle]. 단어 타임스탬프 기반 cue 재구성.
    출력은 data-model 불변식 I1~I5 만족."""

# translate.py  (P3; 백엔드 교체형)
def translate(subtitles: list[Subtitle], target_lang: str,
              *, backend: TranslateBackend | None = None,
              rules: SegmentRules | None = None) -> list[Subtitle]:
    """cue별 번역 → Subtitle.translation[target_lang] 채움. 타임코드 보존."""
# 백엔드 인터페이스: translate_lines(lines: list[str], src: str, tgt: str) -> list[str]

# style.py  (P2)
def apply_style(subtitles: list[Subtitle], preset: StylePreset) -> list[Subtitle]:
    """각 Subtitle.style 을 preset.name 으로 채움(메타 보존)."""
def load_preset(name: str) -> StylePreset: ...
def write_style_sidecar(preset: StylePreset, out_path: str) -> str:
    """name.style.json 사이드카 출력."""

# export.py  (결정적)
def export(subtitles: list[Subtitle], fmt: str, out_path: str,
           *, lang: str | None = None, bom: bool = False,
           newline: str = "\n") -> str:
    """list[Subtitle] → SRT/VTT 파일. fmt in {'srt','vtt'}.
    lang 지정 시 해당 언어 번역 줄(translation[lang])로 출력(다국어 분리 파일)."""

# pipeline.py  (오케스트레이션)
# 모든 실행 옵션을 PipelineOptions 한 자료형으로 묶어 받는다(CLI/앱이 다루기 쉬운 평면 옵션).
@dataclass
class PipelineOptions:
    model_size: str = "large-v3"; language: str | None = "ko"
    glossary: dict[str, str] | None = None
    rules: SegmentRules | None = None          # None이면 default_segment_rules()
    translate_to: str | None = None; preset: str | None = None
    formats: list[str] = ["srt"]; device: str = "auto"
    out_dir: str | None = None; out_stem: str | None = None
    bom: bool = False; newline: str = "\n"
    translate_backend: object | None = None     # translate_to 지정 시 필수(모킹 금지)

def run(video_path: str, options: PipelineOptions,
        progress_cb: ProgressCB | None = None) -> dict:
    """extract_audio → transcribe → correct → segment → (translate) → (apply_style) → export.
    단계별 진행률을 progress_cb 로 보고. 임시 WAV는 완료 시 정리.
    반환: PipelineResult.to_dict() — output_paths / outputs_by_format / language /
    duration / subtitle_count / cps_over_count / cps_over_indices."""
```

**보조 타입(엔진 내부, models.py 외 — pipeline 계약용):**

```python
ProgressCB = Callable[[str, float], None]   # (stage_name, fraction 0.0~1.0)

@dataclass
class PipelineResult:
    subtitles: list[Subtitle]
    output_paths: list[str]                       # 생성된 자막/사이드카 파일 경로들
    outputs_by_format: dict[tuple[str, str | None], str]
    transcript: Transcript
    language: str
    duration: float
    cps_over_indices: list[int]                   # CPS 상한 초과 cue 인덱스(리포트용, AC3.2)
    # run() 은 PipelineResult.to_dict() 로 직렬화해 dict 를 반환한다(CLI/앱은 output_paths 중심).
```

`ProgressCB` / `PipelineResult` 는 `pipeline.py` 에 정의한다(파이프라인 오케스트레이션 전용,
데이터 모델 자료형이 아니므로 `models.py` 에 두지 않는다).

**단계별 입출력 요약(data-model 계약과 일치):**

| 단계 | 입력 | 출력 | 단계 | 결정적 |
|------|------|------|------|--------|
| extract_audio | video_path | wav_path | MVP | — (ffmpeg) |
| transcribe | wav_path, TranscribeOptions | Transcript | MVP | — (모델) |
| correct | Transcript, glossary | Transcript | MVP(글로서리) | ✅ |
| segment | Transcript, SegmentRules | list[Subtitle] | MVP | ✅ |
| translate | list[Subtitle], target_lang | list[Subtitle] | P3 | 백엔드 의존 |
| apply_style | list[Subtitle], StylePreset | list[Subtitle] | P2 | ✅ |
| export | list[Subtitle], fmt, out_path | out_path | MVP | ✅ |

---

## 5. 데이터 흐름과 경계면 검증 포인트 (QA 전달)

```
video ──extract_audio──> wav ──transcribe──> Transcript ──correct──> Transcript'
   ──segment──> list[Subtitle] ──translate(opt)──> ──apply_style(opt)──> ──export──> .srt/.vtt(+.style.json)
```

QA가 검증할 경계면 불변식(data-model §불변식, PRD §5):

- **I1** `Subtitle.start < Subtitle.end`
- **I2** 인접 cue `next.start >= prev.end` (겹침 금지)
- **I3** `index` 1부터 연속
- **I4** `lines` 1~2개, 각 줄 길이 ≤ `max_chars_per_line`(단어 분할 불가 예외 허용)
- **I5** 모든 타임스탬프 ≥ 0, `end ≤ Transcript.duration`
- **보존성**: `correct` / `translate` / `apply_style` 는 타임스탬프를 변경하지 않는다.
- **결정성**: 동일 입력 → `segment` / `export` 동일 출력.

---

## 6. UI 스택 결정 — **PySide6 데스크톱 (확정)**

PRD OQ1(데스크톱 UI 스택) 해소.

| 후보 | 장점 | 단점 | 판정 |
|------|------|------|------|
| **PySide6 (Qt for Python)** | 엔진과 **단일 언어(Python)** — 별도 IPC/사이드카 불필요, 엔진 함수 직접 호출. 드래그앤드롭·진행률 바·`QThread` 백그라운드 워커 우수. PyInstaller로 .exe onedir 패키징 검증됨. LGPL. | 네이티브 위젯 룩(웹만큼 화려하진 않음). | **채택(기본)** |
| Electron / Tauri | 웹 기술 친숙, 풍부한 UI. | Python 엔진을 **사이드카 프로세스**로 띄워 IPC(소켓/STDIO)로 통신해야 함 → 패키징·배포·에러 전파 복잡. 두 런타임(Node+Python) 동봉. | 미채택 |
| 웹(FastAPI + 브라우저) | 원격/협업 확장 용이. | 로컬 단독·오프라인·대용량 파일 처리에 부적합. PRD 비목표(클라우드/협업)와 충돌. | 미채택 |

**결정 근거(요약):** Volo는 *로컬 단독 데스크톱 + 대용량 영상 처리 + Python 엔진* 이 핵심이다.
PySide6는 엔진과 같은 프로세스에서 함수 호출로 직결되어 IPC 비용·패키징 복잡도가 없고, 무거운 STT는
`QThread` 워커로 돌려 진행률을 UI에 콜백(`progress_cb`)으로 흘릴 수 있다. 엔진/UI 분리 원칙은
유지되므로(앱은 엔진을 호출만) 추후 웹 UI로 교체해도 엔진은 불변이다.

**UI ↔ 엔진 연결 패턴(Phase 2 가이드):**
- 앱은 `volo_engine.pipeline.run(...)` 을 `QThread` 워커에서 호출.
- `progress_cb(stage, fraction)` → Qt 시그널로 변환해 진행률 바 갱신.
- 결과 `PipelineResult.subtitles`(=`list[Subtitle]`)를 테이블 뷰에 바인딩. 편집 후에도 자료형 유지.
- `VoloError` 는 잡아서 다이얼로그 메시지(`user_message()`)로 표시(스택트레이스 비노출).

---

## 7. 패키징 / 배포

- **개발 설치:** `pip install -e .[dev]` (엔진+CLI+테스트), UI까지 `pip install -e .[app]`.
- **CLI 엔트리포인트:** `pyproject.toml [project.scripts] volo = "volo_cli.__main__:main"`.
- **배포(권고):** PyInstaller **onedir**(.exe + 의존성 폴더). 모델 가중치(`large-v3`, 수 GB)는
  **동봉하지 않고** 최초 실행 시 다운로드·캐시(`~/.cache/huggingface`, `VOLO_MODEL_CACHE` 로 변경 가능).
  → 배포 용량 최소화, 라이선스/업데이트 단순화. (PRD OQ5 권고안.)
- **ffmpeg:** 시스템 PATH 우선, 없으면 `imageio-ffmpeg` 번들 바이너리. 별도 설치 강제 없음.
- **모델 캐시/대용량 산출물은 `.gitignore`** 로 저장소에서 제외.

---

## 8. PRD OPEN QUESTIONS 처리

| OQ | 처리 | 비고 |
|----|------|------|
| OQ1 UI 스택 | **확정: PySide6 데스크톱**(§6) | 엔진은 직접 함수 호출, 분리 원칙 유지. |
| OQ2 고급 한국어 교정기 | **가정**: MVP는 `correct` 의 글로서리 치환 + 경량 규칙(stdlib·오프라인)만. LLM/외부 교정기는 P2 선택 플러그인 | planner 확인 요청. 오프라인 동작 보장. |
| OQ3 번역 백엔드 | **가정**: P3. 인터페이스 `translate_lines(lines, src, tgt)` 만 확정, 기본 구현은 단계적. 핵심 경로 강제 아님 | planner 확인 요청. |
| OQ4 SRT 줄바꿈/BOM | **가정**: 기본 `newline="\n"`, `bom=False`. export에 `bom`/`newline` 옵션 노출 | qa 실측(프리미어 임포트) 후 기본값 확정. |
| OQ5 패키징/모델 동봉 | **권고**: PyInstaller onedir + 모델 비동봉(런타임 다운로드)(§7) | planner/배포 정책 확인. |

위 가정은 설계 임시 확정이며 ARCHITECTURE에 명시. 변경 시 영향 모듈을 통지한다.

---

## 9. 변경 메모

- 2026-06-19 · 초기 작성 · architect. PRD/data-model/subtitle-domain 정합.
  데이터 모델 코드화(`volo_engine/models.py`), 스캐폴드(pyproject/requirements/.gitignore/README),
  config/errors, 얕은 엔진 `__init__` 확정. UI 스택 = PySide6. 파이프라인 시그니처 계약 확정(§4).
- engine-dev 통지: `audio/transcribe/correct/segment/translate/style/export/pipeline` 시그니처는 §4 그대로 구현.
  결정적 모듈(segment/export/correct/style)은 stdlib만, 무거운 의존성은 함수 내부 import.
- app-dev 통지: CLI 인자 계약(README §실행), UI 연결 패턴(§6). 엔진 호출만, `list[Subtitle]` 유지.
- qa 통지: 경계면 불변식 I1~I5(§5), 보존성/결정성, OQ4 실측 포인트.
```
