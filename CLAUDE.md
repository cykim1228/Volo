# Volo — 프리미어용 AI 자동 자막 툴

Voice + Log. 프리미어 프로 편집자가 "자막을 직접 다는 고통"을 없애는 도구.
영상/오디오 → 로컬 faster-whisper 전사 → 한국어 교정·줄바꿈/타이밍 최적화 → SRT 등 내보내기 → 프리미어 임포트.

## 제품 방향 (확정)
- **형태**: 독립 데스크톱 앱 + 자막파일(SRT/VTT) 내보내기. (프리미어 패널 연동은 향후)
- **STT**: 로컬 `faster-whisper` (API 비용 0, 프라이버시, 한국어 정확도). GPU 자동감지→CPU 폴백.
- **부가가치**: ① 한국어 정확도·문장 교정(+글로서리) ② 자막 줄바꿈·타이밍(CPS) 최적화 ③ 번역/다국어 ④ 스타일 프리셋.
- **핵심 원칙**: 엔진(`volo_engine`)은 UI 무관 순수 라이브러리. UI/CLI는 엔진을 호출만. 모킹 금지(실제 동작 경로).

---

## 하네스: Volo 개발

**목표:** 기획→설계→엔진→앱→검증을 전문 에이전트 팀으로 자동 진행해 Volo를 구현·확장한다.

**에이전트 팀:**
| 에이전트 | 역할 |
|---------|------|
| planner | 제품 명세(PRD)·기능 우선순위·수용 기준 작성 |
| architect | 스택·데이터 모델·파이프라인 인터페이스·디렉토리 구조 설계 |
| engine-dev | Python 코어 엔진 구현(faster-whisper/ffmpeg/세그멘테이션/내보내기/CLI) |
| app-dev | 독립 데스크톱 앱 UI 구현(엔진 호출) |
| qa | 경계면 교차 비교 + 실제 pytest 실행 + 수용 기준 판정 (general-purpose 타입) |

**스킬:**
| 스킬 | 용도 | 사용 에이전트 |
|------|------|-------------|
| volo-spec | PRD/제품 명세 작성 방법론 | planner |
| volo-architecture | 아키텍처·데이터 모델 설계 (+references/data-model.md) | architect |
| volo-engine-dev | 엔진 구현 방법론 (+references/subtitle-domain.md) | engine-dev |
| volo-app-dev | 데스크톱 앱 UI 구현 방법론 | app-dev |
| volo-qa | 통합 검증 방법론 (+references/boundary-checks.md) | qa |
| volo-build | **오케스트레이터** — 팀 전체 워크플로우 조율 | (리더) |

**실행 규칙:**
- Volo 자막 기능 개발/구현/수정/확장 요청 시 `volo-build` 스킬로 에이전트 팀을 통해 처리한다.
- 단순 질문/확인은 팀 없이 직접 응답 가능.
- 모든 에이전트는 `model: "opus"` 사용.
- 중간 산출물: `_workspace/`. 최종 코드/문서는 실제 경로.
- `data-model.md`는 데이터 shape의 단일 진실 원천 — 변경 시 영향 모듈 통지.

**디렉토리 구조:**
```
.claude/
├── agents/
│   ├── planner.md  architect.md  engine-dev.md  app-dev.md  qa.md
└── skills/
    ├── volo-spec/SKILL.md
    ├── volo-architecture/SKILL.md + references/data-model.md
    ├── volo-engine-dev/SKILL.md + references/subtitle-domain.md
    ├── volo-app-dev/SKILL.md
    ├── volo-qa/SKILL.md + references/boundary-checks.md
    └── volo-build/SKILL.md   ← 오케스트레이터
```
프로젝트 코드 구조: `volo_engine/`(코어), `volo_cli/`(CLI), `volo_app/`(UI), `tests/`, `assets/presets/`, `docs/`.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-06-19 | 초기 하네스 구성 (에이전트 5 + 스킬 6) | 전체 | Volo 신규 구축 |
| 2026-06-19 | volo-build 파이프라인 1차 실행 → PRD·아키텍처·엔진·CLI·앱·테스트 생성, QA 46 테스트 통과 | 코드 전체 | 초기 개발 |
| 2026-06-19 | QA 발견 버그 수정: F-2(CLI `--max-cps`/`--max-chars` 추가, AC5.5), F-3(CPS 초과 cue 리포트, AC3.2), F-1(ARCHITECTURE run() 시그니처 정합), F-1b(data-model.md SSOT 정합) | cli/pipeline/segment, docs, data-model.md | 검증 결과 반영 |
| 2026-06-19 | 라이선스 MIT 확정 + 공개 준비(LICENSE, THIRD_PARTY_NOTICES, README 전면 개편, PyInstaller spec, GH Actions release) | 루트 문서/패키징 | 공개 리포 전환 |
| 2026-06-19 | **한국어 STT 품질 강화**: 환각·반복 억제 파라미터(condition_on_previous_text=False, temperature 폴백, no_speech/log_prob/compression/hallucination 임계) + 글로서리→initial_prompt 자동 주입 + `--prompt` + 모델 캐시 경로 연결. 검증 테스트(test_transcribe) 추가 → 50 통과 | models/transcribe/pipeline/cli, subtitle-domain.md | 자동자막 품질 |
| 2026-06-19 | CLI .exe 실제 빌드·스모크 검증(PyInstaller) → **cp949 콘솔 UnicodeEncodeError 수정**(stdout/stderr UTF-8 고정) | volo_cli, packaging | 한국 윈도우 실행 안정성 |
| 2026-06-19 | **데스크톱 GUI 전면 재디자인**: 다크 테마(QSS)+카드 레이아웃+인디고 강조, 스크롤 영역, 헤더. 품질 옵션 UI 노출(인식 힌트/글로서리/CPS·줄길이). 스크린샷(docs/screenshot.png) 추가. PySide6 6.11로 실제 렌더·라이브 실행 검증 | volo_app/*, README | GUI 디자인 |
| 2026-06-19 | **STT 디바이스 자동 폴백**: device=auto에서 GPU(cuda/float16) 로드 실패 시 cuda/int8→cpu/int8 단계 폴백(load_model + _load_attempts). 폴백 테스트 3개 추가 → 53 통과 | transcribe.py, tests | GPU float16 미지원 환경에서도 완주(AC2.3) |
| 2026-06-19 | **모델 다운로드 진행률 표시**: transcribe.prepare_model + _ensure_downloaded(huggingface snapshot_download tqdm_class 후킹)로 'download' 단계 진행률 보고. pipeline이 전사 전 모델 선로드. worker.format_progress가 download를 별도 0~100% 패스로 표시. 디바이스 드롭다운 라벨 명확화(자동/GPU/CPU, currentData). 테스트 5개 추가 → 58 통과 | transcribe/pipeline/worker/main_window, tests | "5% 멈춤"(=무피드백 다운로드) 해소 |
| 2026-06-19 | **README 문서 보강**: GUI 사용법(스크린샷 3종: 초기/진행/결과) + GPU(CUDA) vs CPU 가이드 + FAQ/문제해결(접이식 11항목, 실제 발생 이슈 기반) 추가 | README.md, docs/screenshot*.png | 사용자 온보딩·문제해결 |
| 2026-06-19 | **오디오 전처리(한국어 정확도)**: audio.build_audio_filters(highpass+afftdn 잡음제거, loudnorm 음량정규화) 기본 적용. PipelineOptions.denoise/normalize, CLI --no-denoise/--no-normalize, GUI 체크박스. 실제 ffmpeg 통합검증 + 단위테스트 4개 → 62 통과 | audio/pipeline/cli/main_window, subtitle-domain.md | 잡음·음량 편차 영상 인식률↑ |
| 2026-06-19 | **GUI .exe 빌드 완성**: PyInstaller spec 경로(SPECPATH 절대경로) 수정, config frozen-aware PROJECT_ROOT(번들 프리셋 로드). dist/Volo/Volo.exe(411MB) 빌드→**실행해 GUI 창 검증**→Volo-windows.zip(158MB, 라이선스 동봉) 패키징 | packaging/volo.spec, config.py | 비개발자용 단독 실행파일 배포 |
| 2026-06-19 | **릴리스 파이프라인 감사·수정**(워크플로 적대적 감사): CRITICAL — imageio_ffmpeg/huggingface_hub 지연import라 미동봉 → .exe 가 ffmpeg 못 찾아 자막생성 실패하던 것 발견·수정(spec collect+hiddenimports), 재빌드해 ffmpeg/hf/vad 동봉 검증. release.yml 버전별 zip 이름 + generate_release_notes + 설치 body. RELEASING.md/CHANGELOG.md 신규, README A 섹션 Releases 흐름으로 교체 | packaging/volo.spec, release.yml, README, RELEASING/CHANGELOG | 버전별 Releases 자동배포 |
| 2026-06-22 | **단일 exe(onefile) 배포 추가**: packaging/volo-onefile.spec 신규(단일 Volo.exe), 로컬 빌드·실행 검증. release.yml 이 onefile(.exe) + onedir(.zip) **둘 다 빌드·첨부**. README 다운로드 안내에 단일 exe 옵션 추가. gitignore `!packaging/*.spec`·`*.exe` 보정 | volo-onefile.spec, release.yml, README, .gitignore | "exe 하나만 받아 실행" 요구 |

**알려진 잔여 항목(P2/보류):** F-4(글로서리 대소문자·띄어쓰기 변형 매칭, AC6.2 부분) · F-5(`write_style_sidecar` export/style 중복 — 현재 출력 동일, 통합 시 회귀 위험으로 보류). 자세한 내용은 `_workspace/QA_report.md`.
