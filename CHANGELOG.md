# Changelog

이 프로젝트의 모든 주목할 만한 변경 사항을 이 파일에 기록합니다.

형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르며,
버전 표기는 [유의적 버전(SemVer)](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

### 추가 예정 (로드맵)
- **번역 백엔드 연결** — 현재 인터페이스만 있는 번역 기능에 실제 백엔드를 연결해 언어별 SRT 동시 출력.
- **배치 처리** — 여러 영상을 한 번에 큐로 처리.
- **화자 분리(diarization)** — 화자별 라벨링/분할.

## [0.1.0] - 2026-06-19

첫 공개 릴리스(MVP). 영상 하나를 넣으면 타임코드까지 맞춰진 한국어 자막(SRT/VTT)을 만들어
프리미어 프로 캡션 트랙으로 임포트할 수 있습니다. CLI 와 데스크톱 GUI, Windows `.exe` 패키징 포함.

### 추가됨
- **로컬 faster-whisper STT** — 로컬 추론으로 영상/오디오를 전사. GPU(CUDA) 자동 감지, 없으면 CPU(int8)로 자동 폴백(구형 GPU의 float16 미지원 시 `GPU int8 → CPU` 폴백 포함). API 비용 0, 영상 외부 전송 없음.
- **한국어 교정 + 글로서리** — 전사 결과를 한국어 가독성에 맞춰 교정하고, 글로서리 JSON(`{"원표기":"교정표기"}`)으로 고유명사·브랜드명 오인식을 강제 교정.
- **인식 힌트(initial_prompt)** — 영상 주제·전문용어를 힌트로 넣어 전사 정확도를 높임.
- **CPS / 줄 길이 세그멘테이션** — 초당 글자수(CPS) 상한·한 줄 글자수·표시시간 기준으로 자막을 자동 분할/병합. 맞추지 못한 cue 는 "N개 cue CPS 초과" 경고로 표시.
- **오디오 전처리** — denoise + loudnorm 으로 인식 안정성 향상.
- **번역 인터페이스** — 언어별 자막 출력을 위한 번역 단계 인터페이스(실제 백엔드 연결은 로드맵).
- **스타일 프리셋** — 폰트/색/위치 프리셋을 사이드카(`*.style.json`)로 출력해 프리미어 캡션 트랙에 적용. 기본 제공: `default` / `youtube` / `interview`.
- **SRT / VTT 내보내기** — 표준 자막 포맷 출력. UTF-8 BOM(`--bom`)·CRLF(`--crlf`) 옵션 지원.
- **CLI (`volo`)** — 영상 → 자막 단일 명령. 모델/언어/디바이스/포맷/CPS/줄길이/글로서리/번역/프리셋 옵션. UTF-8 출력 고정(한국어 Windows 호환).
- **데스크톱 GUI (`volo-app`, PySide6)** — 드래그앤드롭 입력, 옵션 패널, **모델 다운로드/처리 진행률 표시**, 결과 표 미리보기·인라인 편집, 내보내기.
- **.exe 패키징** — PyInstaller onedir 빌드(`packaging/volo.spec`)와 태그 푸시 시 Windows 러너에서 `Volo-windows.zip` 을 만들어 GitHub Release 에 첨부하는 워크플로(`.github/workflows/release.yml`).

### 비고
- 모델 가중치는 동봉하지 않습니다. `.exe`/소스 **최초 실행 시 자동 다운로드**되어 `~/.cache/huggingface`(또는 `VOLO_MODEL_CACHE`/`HF_HOME`)에 캐시됩니다(`large-v3` 약 3GB, `medium` 약 1.5GB). 다운로드 후에는 오프라인 동작.
- ffmpeg 는 시스템 PATH 우선, 없으면 `imageio-ffmpeg` 번들 바이너리로 자동 폴백(수동 설치 불필요).
- Volo 본체는 MIT. 번들 배포 시 PySide6(LGPL-3.0)·FFmpeg(LGPL/GPL) 고지는 `THIRD_PARTY_NOTICES.md` 참조.

[Unreleased]: https://github.com/<OWNER>/<REPO>/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/<OWNER>/<REPO>/releases/tag/v0.1.0
