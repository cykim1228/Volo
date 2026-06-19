---
name: volo-architecture
description: Volo의 기술 아키텍처를 설계·갱신하는 방법론. 엔진(Python)과 UI의 분리, 캐노니컬 데이터 모델, 파이프라인 인터페이스, 디렉토리 구조, 패키징을 정의한다. architect 에이전트가 사용. "Volo 아키텍처", "데이터 모델 설계", "모듈 경계", "스택 결정", "파이프라인 인터페이스", "구조 설계 다시/수정" 요청 시 사용.
---

# volo-architecture — Volo 기술 설계

architect 에이전트가 PRD를 기술 설계로 변환할 때 따르는 방법론.

## 컨텍스트 확인 (먼저)
- `docs/ARCHITECTURE.md`, `volo_engine/models.py` 존재 여부 확인. 있으면 읽고 변경분만 수정. 데이터 모델을 바꾸면 영향 모듈을 목록화해 통지.
- 입력: `docs/PRD.md`(없으면 planner에 요청).

## 핵심 설계 원칙
1. **엔진/UI 완전 분리.** `volo_engine`은 UI를 import하지 않는 순수 라이브러리. UI·CLI는 엔진을 호출만 한다. 이 경계가 향후 데스크톱→웹 UI 교체를 가능케 한다.
2. **데이터 모델 = 단일 진실 원천.** 모든 단계가 `models.py`의 타입으로만 통신. 자세한 자료형 정의는 `references/data-model.md` 참조 — 이 파일을 읽고 `volo_engine/models.py`를 실제 코드로 작성한다.
3. **파이프라인 = 교체 가능한 단계.** 각 단계는 명시적 입력/출력 타입을 갖고, 생략·교체 가능.

## 확정된 스택 (기본값)
- **언어/엔진**: Python 3.11+. STT는 `faster-whisper`(CTranslate2). 오디오는 `ffmpeg`(시스템 바이너리 또는 `imageio-ffmpeg`).
- **UI 스택 결정**: 기본 권고 **PySide6 데스크톱**(단일 언어, PyInstaller로 .exe 패키징 용이, 드래그앤드롭/진행률/스레딩 우수). 대안 Electron/Tauri(웹 UI 친숙하나 Python 사이드카 패키징 복잡)는 트레이드오프를 ARCHITECTURE.md에 적고 결정. 어느 쪽이든 **엔진은 UI 무관 라이브러리**로 유지.
- **패키징**: 엔진은 `pyproject.toml` 패키지 + `volo` CLI 엔트리포인트. 최종 배포는 PyInstaller onedir(.exe + 모델 캐시 분리).

## 파이프라인 인터페이스 (계약)
```
extract_audio(video_path) -> wav_path
transcribe(wav_path, opts) -> Transcript
correct(Transcript, glossary) -> Transcript
segment(Transcript, rules) -> list[Subtitle]
translate(list[Subtitle], target_lang) -> list[Subtitle]   # 선택
apply_style(list[Subtitle], preset) -> list[Subtitle]       # 선택
export(list[Subtitle], fmt, out_path) -> out_path
```
`pipeline.run(video_path, options, progress_cb)`가 위를 순차 실행하고 단계별 진행률을 콜백으로 보고한다. 각 타입 정의는 `references/data-model.md`.

## 디렉토리 구조 (기준)
```
Volo/
├── volo_engine/   # UI 무관 코어 (models, audio, transcribe, correct, segment, translate, style, export, pipeline, config)
├── volo_cli/      # CLI 진입점 (엔진 호출)
├── volo_app/      # 데스크톱 UI (엔진 호출)
├── assets/presets/   # 스타일 프리셋, 글로서리 샘플
├── tests/         # pytest (결정적 모듈)
├── docs/          # PRD.md, ARCHITECTURE.md
├── pyproject.toml, requirements.txt, README.md, .gitignore
```

## 산출
- `docs/ARCHITECTURE.md`(스택·근거·인터페이스·구조·패키징·결정필요), `volo_engine/models.py`(실제 코드), 스캐폴드 파일(`pyproject.toml`/`requirements.txt`/`.gitignore`/`README.md` 골격). 중간: `_workspace/02_architect_*.md`.

## 갱신 시
데이터 모델·인터페이스 변경은 영향 모듈 목록과 함께 engine-dev·app-dev·qa에 통지하고 ARCHITECTURE.md 변경 메모에 기록.
