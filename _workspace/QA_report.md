# Volo QA 보고서

> 작성: qa 에이전트 · 2026-06-19
> 대상: `volo_engine/*`, `volo_cli/*`, `volo_app/*`, `docs/PRD.md`, `docs/ARCHITECTURE.md`
> 방법: 경계면 교차 비교(boundary-checks A~G) + 결정적 모듈 pytest 실제 실행 + PRD 수용 기준 대조
> 원칙: 생성-검증 분리 — QA는 버그를 **보고만** 하고 수정하지 않는다.

---

## 0. 실행 환경 사실 (정직 보고)

- **초기 가정(작업지시): "Python/ffmpeg 미설치, pytest 런타임 실행 불가".**
  - `python` / `python3` 는 WindowsApps 실행 별칭 스텁이 맞다(실행 시
    "Python was not found …", exit 49). `ffmpeg` 는 PATH·`command -v` 모두 부재.
  - **그러나 실제 동작하는 Python 이 존재한다**: `C:\Users\cykim\miniconda3\python.exe`
    (Python **3.13.5**, conda 25.7.0). 이 인터프리터로는 stdlib import·실행이 정상.
- **pytest 는 처음엔 미설치**였다(`No module named pytest`). 결정적 모듈 검증을 위해
  miniconda 환경에 `pip install pytest` 로 **임시 설치 → 테스트 실행 → 검증 후 제거**하여
  환경을 원상복구했다(pytest/pluggy/iniconfig 제거 완료).
- **ffmpeg / faster-whisper / PySide6 는 검증하지 않았다**: 무거운 의존성·외부 바이너리는
  이 머신에 없고 작업 범위 밖이다. 해당 단계(audio/transcribe/UI 실행)는 **정적 경계면
  검증 + 의존성 주입 인터페이스 검증**으로 대체했고, 수동 검증 절차를 아래 판정표에 남겼다.

### pytest 실제 실행 출력 (그대로 기록)

1) 작업지시 명령 그대로 (`python` = WindowsApps 스텁):

```
$ python -m pytest tests -q
Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases.
EXIT_CODE=49
```

2) 실제 동작 Python (miniconda) + 임시 설치한 pytest:

```
$ /c/Users/cykim/miniconda3/python -m pytest tests -q
..............................................                           [100%]
EXIT_CODE=0

$ /c/Users/cykim/miniconda3/python -m pytest tests -v
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-9.1.0, pluggy-1.5.0
rootdir: C:\Projects\Volo
configfile: pyproject.toml
plugins: anyio-4.12.0
collected 46 items

tests\test_export.py .............................                       [ 63%]
tests\test_segment.py .................                                  [100%]

============================= 46 passed in 0.07s ==============================
```

**결론: 결정적 모듈(models/segment/export) 46개 테스트 전부 통과(0.07s).**
손 추적으로도 통과가 타당함을 확인했다(불변식·왕복 파싱 모두 만족).

---

## 1. 작성한 테스트 (산출물)

| 파일 | 내용 | 개수 |
|------|------|------|
| `tests/conftest.py` | 공통 헬퍼: 데이터 팩토리, SRT/VTT 왕복 파서(`parse_srt`/`parse_vtt`), 불변식 검사기(`assert_subtitle_invariants` I1~I5), CPS 계산, fixtures. stdlib + `volo_engine.models/segment/export` 만 import. | (헬퍼) |
| `tests/test_segment.py` | 불변식(겹침없음/인덱스연속/줄길이/CPS/표시시간), 분할규칙(문장부호·글자수예산), word-없는 폴백, 정렬, 결정성, duration 클램프. | 17 |
| `tests/test_export.py` | SRT/VTT 왕복 파싱, 타임코드 형식·라운드트립, UTF-8/BOM, CRLF, 인덱스 재부여, 번역 줄 출력, 미지원 포맷 오류, 내장 개행, 결정성. | 29 |

전부 **순수 stdlib + 결정적 엔진 모듈만** import → 무거운 의존성 없이 수집·실행 가능
(ARCHITECTURE §1.5 얕은 `__init__` 정책과 정합 확인).

---

## 2. 경계면 교차 비교 (boundary-checks A~G)

각 항목은 **두 개 이상 파일을 동시에 읽고** shape/타입/시그니처 일치를 본 결과다.

### A. 데이터 모델 정합성
- ✅ 각 단계 입출력 타입이 `models.py` 자료형과 일치. 타임스탬프는 전 구간 float 초
  (포맷 변환은 `export.format_timestamp` 단일 지점에서만).
- ✅ `Subtitle.lines` 는 `list[str]`, `translation` 은 `dict[str,list[str]] | None`.
  segment/translate/export 모두 이 shape 준수.
- ⚠️ **드리프트 2건**(B-1, B-2 참조): `models.Subtitle.speaker` 추가 필드,
  `models.Transcript.segments` 기본값 추가 — 캐노니컬 `data-model.md` 와 불일치.

### B. SRT 포맷 유효성 (export 출력 파싱)
- ✅ cue 빈 줄 구분, 인덱스 1부터 연속(출력 순서로 **재부여** — `Subtitle.index` 무시),
  타임코드 `HH:MM:SS,mmm`(쉼표·3자리·0패딩), UTF-8(기본 BOM 없음), 한글 보존.
  `render_srt` ↔ `parse_srt` 왕복 테스트로 검증(타임 ±1ms, 텍스트 동일).
- ✅ 줄 안 내장 개행(`"줄1\n줄2"`)도 `_cue_lines` 가 정규화해 cue 구조 보존.

### C. VTT 포맷
- ✅ `WEBVTT` 헤더 시작, 타임코드 점(`.`) 구분자. SRT/VTT 동일 입력에서 cue 수·타임·텍스트 일치(AC7.2 테스트).

### D. 세그멘테이션 규칙 (segment 출력)
- ✅ 줄 길이 ≤ `max_chars_per_line`(분할 가능 시), cue 표시시간 보정, 인접 간격 `min_gap`,
  인덱스 재부여 — 불변식 I1~I5 테스트 통과.
- ⚠️ **CPS 상한은 "가용 시간이 있을 때만" 보장**(설계상 명시). 다음 cue·duration 상한으로
  end 확장이 막히면 CPS 가 `max_cps` 를 초과할 수 있다(런타임 재현: duration=0.96s,
  CPS 20.8 > 17.0). 불변식 I1~I5 는 여전히 유지. → **AC3.2 의 "예외 리포트" 조건**이며
  버그는 아니나, CLI/UI 가 이 초과 cue 를 사용자에게 알리는 경로는 없음(개선점, F-3).

### E. 인터페이스 정합성 (CLI/앱 ↔ 엔진)
- ✅ **런타임 호출부는 일관**: CLI(`volo_cli/__main__.py:319`)와 워커
  (`volo_app/worker.py:155`)가 모두 `run(video_path, options: PipelineOptions, progress_cb=)`
  를 호출. 실제 `pipeline.run` 시그니처와 일치.
- ✅ `progress_cb(stage, ratio)` 계약 일치: `pipeline._STAGE_*` 문자열 7종 ==
  `worker.STAGE_LABELS`/`STAGE_WEIGHTS`/`_STAGE_ORDER` 키 집합. `STAGE_WEIGHTS` 합=1.0,
  `overall_ratio` 단조 비감소(런타임 확인).
- ✅ `transcribe.ProgressCB` 는 `pipeline.ProgressCB` 와 동일 시그니처(의도적 로컬 별칭, 순환 import 회피).
- ✅ 엔진 예외 → 사용자 메시지 변환: CLI `main()` 이 `VoloError.user_message()` 출력,
  워커 `_format_exception` 이 `VoloError` 분기. 스택트레이스 비노출.
- ⚠️ **문서-코드 시그니처 드리프트**(F-1): `ARCHITECTURE.md §4` 의 `run(...)` 키워드
  시그니처(`transcribe_options=`, `target_langs=`, `out_path=`, `fmt=`, `model=` …)와
  실제 `PipelineOptions` 기반 시그니처가 다름. **호출부가 모두 실제 시그니처를 쓰므로
  런타임 버그 아님**(코드 docstring 에 의도적 차이 명시). 단 문서가 오해를 부른다.

### F. 폴백·에러 경로 (정적 검증)
- ✅ ffmpeg 미설치 → `resolve_ffmpeg` 가 `VoloDependencyError` + 설치 안내(`_FFMPEG_INSTALL_HINT`). 조용한 실패 아님(AC1.3 코드 경로 확인, 실제 ffmpeg 미실행).
- ✅ CUDA 없을 때 CPU 폴백: `resolve_device("auto")` → `_cuda_available()` False → `("cpu","int8")`. (실제 추론 미실행 — faster-whisper 미설치.)
- ✅ 모델 다운로드/로딩 실패 → `VoloModelError` + 네트워크/캐시/디바이스 안내.
- ✅ 번역 백엔드 미주입 → `TranslateBackendNotConfiguredError`(모킹 금지 — 런타임 확인).

### G. 수용 기준 매핑 → §3 판정표.

---

## 3. PRD 수용 기준 판정표

판정: **충족** / **미충족(버그)** / **검증불가**(이유·수동절차).

| AC | 내용 | 판정 | 근거 |
|----|------|------|------|
| AC1.1 | 16kHz mono PCM WAV 생성 | 검증불가 | ffmpeg 미설치. `extract_audio` 명령 인자(`-ac 1 -ar 16000 -c:a pcm_s16le`) 정적 확인. **수동**: ffmpeg 설치 후 mp4 → WAV 헤더 검사. |
| AC1.2 | PATH 없으면 imageio-ffmpeg 폴백 | 검증불가 | imageio-ffmpeg 미설치. `resolve_ffmpeg` 폴백 분기 정적 확인. |
| AC1.3 | ffmpeg 부재 시 비0 + 안내(스택트레이스 아님) | 충족(정적) | `VoloDependencyError`+`hint`, CLI/워커가 `user_message()` 로 변환. |
| AC1.4 | 임시 WAV 정리 | 충족(정적) | `pipeline.run` finally 블록 `_cleanup_tmp`; `extract_audio` 실패 시 `_cleanup`. |
| AC2.1 | `Transcript.language/duration/segments` 정상 | 검증불가 | faster-whisper 미설치. `transcribe` 조립 로직 정적 확인(duration 0이면 마지막 seg.end 보완). **수동**: 모델 설치 후 한국어 영상 전사. |
| AC2.2 | `word_timestamps` 채움, `0<=prob<=1`, `start<=end` | 검증불가 | `_convert_words` 가 `probability`→`prob` 매핑. prob 범위 클램프는 없음(입력 신뢰). |
| AC2.3 | device=auto, GPU/CPU 예외없이 완주 | 검증불가 | `resolve_device` 폴백 로직 정적 확인(CUDA 감지 실패→CPU). |
| AC2.4 | `transcribe(..., model=가짜)` 주입 사용 | 충족(정적) | `if model is None: model = load_model(opts)` — 주입 시 그대로 사용. **모킹 금지 원칙과 정합(주입은 실제 호출경로 검증 수단).** |
| AC2.5 | 진행률 0→1 단조 증가 | 충족(정적) | `transcribe` 가 `last_ratio` max-클램프로 단조 보장 + 종료 시 1.0 보고. |
| **AC3.1** | 출력 I1~I5 만족 | **충족** | `test_segment.py` 불변식 테스트 통과. |
| **AC3.2** | 어떤 cue 도 CPS ≤ max_cps(분할불가 예외 리포트) | **부분충족** | 가용 시간 있으면 충족(테스트). **시간 확장 불가 시 초과 가능**(설계 명시) → 초과 cue 리포트/경고 경로 부재(F-3). |
| **AC3.3** | min_duration ≤ 표시시간 ≤ max_duration(보정 후) | **충족** | `test_min_duration_enforced`/`test_max_duration_respected` 통과(가용 범위 내). |
| **AC3.4** | 어절 경계 분할·조사/어미 고아 회피 | **충족** | `_wrap_two_lines` 어절 경계 + `_ORPHAN_PARTICLES` 페널티. 줄길이 테스트 통과. |
| **AC3.5** | 동일 입력 결정적 | **충족** | `test_determinism` 통과. |
| **AC4.1** | SRT 구조(index→타임코드→줄→빈줄) | **충족** | `test_render_srt_structure` 통과. |
| **AC4.2** | 쉼표+밀리초3자리, 라운드트립 ±1ms | **충족** | `test_format_timestamp_*`/`test_srt_timecode_format_strict` 통과(버림 단위 일치). |
| **AC4.3** | UTF-8(기본 BOM 없음), 재파싱 보존 | **충족** | `test_srt_roundtrip_preserves_content`/`test_srt_utf8_no_bom_by_default` 통과. |
| **AC4.4** | 인덱스 1부터 연속, 시간 오름차순 | **충족** | `test_srt_index_one_based_contiguous` 통과(Subtitle.index 무시·재부여). |
| AC5.1 | `volo <in> --out` 한 명령 E2E | 검증불가 | ffmpeg/모델 미설치. CLI→`pipeline.run` 배선 정적 확인. **수동**: 의존성 설치 후 실행. |
| AC5.2 | 10분 영상 산출 SRT 가 I1~I5+AC4.* | 검증불가 | 실제 영상·모델 필요. |
| AC5.3 | 잘못된 입력/환경부재 → 비0 + 한 줄 원인 | 충족(정적) | `main()` `VoloError` 캐치 → `user_message()`, return 1. `run` 이 입력 경로 검증(`VoloInputError`). |
| AC5.4 | `--glossary` 반영 | 충족(부분) | `_load_glossary`→`PipelineOptions.glossary`→`correct`. 글로서리 치환 자체는 런타임 확인(아래). |
| **AC5.5** | `--max-cps`/`--max-chars` 가 세그멘테이션에 반영 | **미충족(버그 F-2)** | **CLI 에 해당 인자 없음.** `_options_from_args` 가 `rules=None` 고정 → 사용자가 CPS/줄길이 조정 불가. |
| **AC6.1** | 글로서리 치환 + 타임스탬프 불변 | **충족** | 런타임 확인: `correct(tr,{'파이선':'파이썬'})` 후 word/segment start·end·duration 동일, 표기 치환됨. |
| AC6.2 | 띄어쓰기/대소문자 변형 매칭 | 부분충족 | ASCII 키는 단어경계 치환(대소문자는 변형 매칭 **안 함** — `re.escape` 그대로). 띄어쓰기 변형 정규화 로직 없음. → **AC6.2 "대소문자/띄어쓰기 변형" 부분 미충족**(경량, F-4). |
| **AC6.3** | 교정 후 segment/word 개수·시간 보존 | **충족** | 런타임 확인: `replace` 로 텍스트만 교체, 구조 보존. |
| **AC7.1** | WEBVTT 헤더 + 점 구분자 + 밀리초3자리 | **충족** | `test_render_vtt_header_and_dot_separator` 통과. |
| **AC7.2** | SRT/VTT cue 수·타임·텍스트 일치 | **충족** | `test_srt_vtt_same_cues_match` 통과. |
| AC8.1~8.3 | 데스크톱 UI E2E/편집/진행률 | 검증불가 | PySide6 미설치. `main_window`/`worker` 배선·시그널 정합 정적 확인(progress→setValue, 편집→`export` 직접 호출, `parse_subtitle_file` 왕복). **수동**: `pip install .[app]` 후 GUI. |
| AC9.1 | `Subtitle.style` 프리셋 이름 채움 | 충족 | 런타임 확인: `apply_style` 후 `style=='default'`, 입력 비변형. |
| AC9.2 | `name.style.json` 사이드카 생성·속성 보유 | 충족(정적) | `export.write_style_sidecar` `asdict(preset)` 직렬화. 프리셋 JSON 3종 필드 == `StylePreset`. ⚠️ 중복구현(F-5). |
| AC10.1 | translation[tgt] 채움 + 타임코드 보존 | 충족 | 런타임 확인(가짜 백엔드 주입): start/end/index 불변, translation 채움. |
| AC10.2 | `name.ko.srt`/`name.en.srt` 분리 + 각 AC4.* | 충족(정적) | `pipeline._export_all` 가 `(None,src_lang)`,`(tgt,tgt)` 타깃으로 언어 접미사 파일 생성. |
| AC10.3 | 가짜 백엔드 주입으로 인터페이스 동작 | 충족 | 런타임 확인: `TranslateBackend.translate_lines` 프로토콜로 동작. |
| AC11.* | 배치 | 검증불가/미구현 | F11=P3. CLI/UI 단일 파일만(UI: "외 N개 무시"). 범위 밖. |
| AC12.* | 화자 분리 | 검증불가/미구현 | F12=P3. `speaker` 필드만 존재, 채우는 로직 없음. |

---

## 4. 발견 버그 / 불일치 목록

> 심각도: **치명(경계면)** = 런타임 데이터 shape/계약 깨짐 또는 수용기준 직접 미충족.
> **경미** = 문서 드리프트·개선점(런타임 정상).

### 치명적 경계면 버그

**[F-2] (치명·수용기준 미충족) CLI 에 `--max-cps`/`--max-chars` 옵션 부재 → AC5.5 미충족**
- 위치: `volo_cli/__main__.py` `build_parser()` / `_options_from_args()` (line 252~282).
- 현상: PRD F5/AC5.5 는 `--max-cps`, `--max-chars` 로 세그멘테이션 결과를 조정할 수 있어야
  한다고 명시. 그러나 파서에 두 인자가 **없고**, `_options_from_args` 는 `rules=None` 으로
  고정해 항상 기본 `SegmentRules` 만 사용한다(line 272).
- 기대값: `--max-cps`/`--max-chars` 인자 추가 → `SegmentRules(max_cps=…, max_chars_per_line=…)`
  구성 → `PipelineOptions.rules` 로 전달. (엔진/`PipelineOptions.rules` 는 이미 이를 지원하므로
  CLI 배선만 추가하면 된다.)
- 담당: **app-dev**.

**[F-3] (치명도 중·AC3.2 부분) CPS 초과 cue 의 사용자 리포트 경로 부재**
- 위치: `volo_engine/segment.py` `_fix_timing` (CPS 보정) ↔ `pipeline.run` ↔ CLI/UI.
- 현상: 시간 확장 여유가 없으면 CPS 가 `max_cps` 를 초과할 수 있다(런타임 재현 CPS 20.8>17).
  설계상 허용되지만, AC3.2 는 "분할 불가 예외는 **리포트**"를 요구. 현재 초과 cue 를 집계해
  CLI/UI 로 알리는 경로가 없다(조용히 초과).
- 기대값: `segment` 또는 `pipeline` 이 CPS 초과 cue 목록을 결과/경고로 노출(예:
  `PipelineResult` 에 경고 필드, CLI 가 "N개 cue CPS 초과" 출력).
- 담당: **engine-dev**(집계) + **app-dev**(노출). 또는 architect 판단(설계상 수용 시 AC3.2 문구 완화).

### 경미 (문서 드리프트 / 단일 진실 원천 불일치)

**[F-1] (경미·문서) `ARCHITECTURE.md §4` 의 `run(...)` 시그니처와 구현 불일치**
- 위치: `docs/ARCHITECTURE.md` §4 (line 140~152) ↔ `volo_engine/pipeline.py:154`.
- 현상: 문서는 `run(video_path, *, transcribe_options=, segment_rules=, glossary=,
  target_langs=, style_preset=, out_path=, fmt="srt", model=, progress_cb=)` 로,
  반환은 `PipelineResult`. 실제는 `run(video_path, options: PipelineOptions, progress_cb=)`,
  반환은 `dict`(`to_dict()`). **모든 호출부가 실제 시그니처를 쓰므로 런타임 버그 아님.**
- 기대값: 문서를 `PipelineOptions` 기반 실제 계약으로 갱신(또는 코드 docstring 의 의도 명시를
  문서에도 반영). 담당: **architect**.

**[F-1b] (경미·단일 진실 원천) `models.py` ↔ `data-model.md` 자료형 드리프트 2건**
- 위치: `volo_engine/models.py` ↔ `.claude/skills/volo-architecture/references/data-model.md`.
  - `Subtitle.speaker: str | None = None` — 코드에만 존재(캐노니컬 정의에 없음). 추가 필드라
    export/segment 깨짐 없음(additive). 
  - `Transcript.segments: list[Segment] = field(default_factory=list)` — 코드는 기본값 부여,
    캐노니컬은 필수. `Transcript(language=, duration=)` 만으로 생성 시 **빈 transcript 가
    조용히 만들어진다**(QA 트레이싱 중 실제로 혼동 유발). 호출부(transcribe)는 항상 segments 를
    채우므로 런타임 영향은 없으나, 단일 진실 원천 위반.
- 기대값: data-model.md 를 코드에 맞춰 갱신하거나, 코드를 캐노니컬에 맞춤. 변경 시 영향 통지.
  담당: **architect**.

**[F-4] (경미·AC6.2 부분) 글로서리가 대소문자/띄어쓰기 변형을 매칭하지 않음**
- 위치: `volo_engine/correct.py` `apply_glossary` (line 122~158).
- 현상: AC6.2 는 "띄어쓰기/대소문자 변형도 매칭"을 요구. 현재 ASCII 키는 `re.escape` 로
  **정확 일치**(대소문자 구분), 한글 키는 부분 문자열 정확 일치. 변형 흡수 없음.
- 기대값: 케이스 셋 정의 후 대소문자 무시(`re.IGNORECASE`)·공백 정규화 옵션. MVP 범위상
  글로서리 정확 치환은 동작하므로 치명 아님. 담당: **engine-dev**(확인 필요: AC6.2 가 MVP 인지).

**[F-5] (경미·중복) `write_style_sidecar` 가 export.py·style.py 양쪽에 중복 정의**
- 위치: `volo_engine/export.py:274` ↔ `volo_engine/style.py:194`.
- 현상: 동일 이름 함수 2개. 경로 도출 로직이 미묘하게 다름(export: `splitext`+`sort_keys=True`,
  style: `with_name(stem+suffix)`+정렬없음). 현재 입력(`<stem>.<lang>.srt`)에선 결과 동일.
  `pipeline` 은 export 판을 사용. ARCHITECTURE §4 는 style.py 에 둔다고 명시.
- 위험: 두 구현이 향후 갈라지면 사이드카 경로/내용 불일치 가능. 단일화 권장.
- 담당: **engine-dev/architect**.

---

## 5. 회귀/재검증 메모

- 기존 `_workspace/QA_report.md` 없음 → 초회 검증.
- 결정적 모듈은 외부 의존 없이 항상 재실행 가능. `tests/` 가 회귀 가드로 남는다.
- **다음 재호출 시 우선 점검**: (1) F-2 CLI 옵션 추가 후 AC5.5 재검증,
  (2) ffmpeg/faster-whisper/PySide6 설치 환경에서 AC1.*/AC2.*/AC5.1/AC8.* 수동 검증,
  (3) F-1/F-1b 문서·모델 정합 갱신 여부.

---

## 6. 요약

- **결정적 모듈 검증: 46 tests PASS (segment 17 / export 29), exit 0.** 런타임 실제 실행함
  (단, 작업지시상의 "미실행" 전제와 달리 miniconda Python 이 존재해 임시 pytest 설치로 실행).
- **무거운 의존성 경로(audio/transcribe/UI)는 미실행** — 정적 경계면 + 의존성 주입 인터페이스
  검증으로 대체, 수동 절차 명시.
- **치명적 경계면 버그: 1건(F-2, AC5.5 직접 미충족) + 준치명 1건(F-3, AC3.2 리포트 부재).**
  나머지(F-1/F-1b/F-4/F-5)는 문서 드리프트·개선점으로 런타임 정상.

---

## 7. 수정 반영 및 재검증 (오케스트레이터, 2026-06-19)

생성-검증 분리에 따라 QA 보고 후 오케스트레이터가 수정·재검증했다.

| ID | 조치 | 결과 |
|----|------|------|
| **F-2** | `volo_cli/__main__.py` 에 `--max-cps`/`--max-chars` 추가 + `_build_segment_rules()` 로 `SegmentRules` 구성(값≤0 거부). | **해결** — AC5.5 충족. 재검증: 파서가 두 인자를 받고 `PipelineOptions.rules` 에 반영(`max_cps=14, max_chars=16` 확인), 미지정 시 `rules=None`. |
| **F-3** | `segment.cps_exceeding()` 추가 → `pipeline.run` 이 `cps_over_indices`/`cps_over_count` 를 결과 dict 에 노출 → CLI 가 "경고: N개 cue CPS 초과" 출력. | **해결** — AC3.2 리포트 경로 확보. 재검증: 초과 cue 집계·dict 키 확인. |
| **F-1** | `docs/ARCHITECTURE.md §4` 의 `run()` 시그니처를 실제 `PipelineOptions` 기반 + dict 반환으로 갱신. | **해결** — 문서/코드 정합. |
| **F-1b** | `data-model.md` 에 `Subtitle.speaker` 추가, `Transcript.segments` 기본값 명시(코드에 맞춰 SSOT 정합). | **해결**. |
| F-4 | 글로서리 변형 매칭 — AC6.2 가 P2 후보로 판단, 정확 치환은 동작하므로 **보류**. | 잔여(P2). |
| F-5 | `write_style_sidecar` 중복 — 현재 출력 동일, 통합 시 통과 테스트 회귀 위험 → 범위 최소화로 **보류**. | 잔여(경미). |

**재검증 실행(miniconda Python 3.13.5):**
- 신규/수정 코드 단위 검증: compile 18파일 OK, cps_exceeding/CLI 옵션/PipelineResult.to_dict 모두 통과.
- **회귀: `pytest tests -q` → 46 passed(0 회귀).** (pytest 임시 설치→실행→제거로 환경 원복.)
- 캐시(`__pycache__`/`.pytest_cache`) 정리 완료.
