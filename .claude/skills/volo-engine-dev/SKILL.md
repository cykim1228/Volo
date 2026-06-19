---
name: volo-engine-dev
description: Volo 파이썬 코어 엔진(volo_engine) 구현 방법론. faster-whisper STT, ffmpeg 오디오 추출, 한국어 교정·글로서리, CPS/줄길이 기반 자막 세그멘테이션, 번역, 스타일 프리셋, SRT/VTT/프리미어 캡션 내보내기, CLI를 실제 동작 코드로 구현한다. engine-dev 에이전트가 사용. "Volo 엔진 구현", "faster-whisper 연동", "자막 세그멘테이션", "SRT 내보내기", "자막 엔진 수정/보완" 요청 시 사용.
---

# volo-engine-dev — Volo 엔진 구현

engine-dev 에이전트가 `volo_engine` 코어를 구현할 때 따르는 방법론. 모킹 금지 — 실제 동작 경로.

## 컨텍스트 확인 (먼저)
- `docs/ARCHITECTURE.md`와 `volo_engine/models.py`를 읽고 데이터 모델·인터페이스를 확인한다(없으면 architect에 요청).
- 기존 `volo_engine/*` 모듈이 있으면 읽고 변경분만 수정.

## 구현 순서 (의존성 기준)
1. `models.py`(architect 제공) → 2. `config.py` → 3. `audio.py` → 4. `transcribe.py` → 5. `correct.py` → 6. `segment.py` → 7. `translate.py` → 8. `style.py` → 9. `export.py` → 10. `pipeline.py` → 11. `volo_cli/`.

`segment.py`·`export.py`·`correct.py`는 **외부 의존 없는 결정적 로직**으로 분리해 pytest 가능하게 한다(QA가 실행). `transcribe.py`는 모델 객체를 의존성 주입받아 호출부를 테스트 가능하게 설계.

## 핵심 구현 규칙
- **데이터 모델 준수.** 단계 간 데이터는 `models.py` 타입으로만. 임의 dict로 shape 깨지 않기.
- **모킹 금지.** faster-whisper·ffmpeg 실제 호출. 단, 무거운 추론을 분리해 결정적 부분은 독립 테스트 가능하게.
- **폴백·에러 메시지.** ffmpeg 미설치/모델 다운로드 실패/CUDA 없음 → 명확한 메시지 + CPU 폴백. 조용한 실패 금지.
- **진행률 콜백.** `pipeline.run`은 `progress_cb(stage: str, ratio: float)` 형태로 단계 진행을 보고.

## 도메인 지식 (필독)
faster-whisper 사용법, 한국어 자막 관례(CPS·줄 길이·분할 규칙), 세그멘테이션 알고리즘, SRT/VTT/프리미어 포맷 스펙, 교정·번역 접근은 모두 `references/subtitle-domain.md`에 있다. 구현 전 해당 절을 읽는다.

## 산출
- `volo_engine/*.py`, `volo_cli/*`, `assets/presets/`(기본 스타일·글로서리 샘플), `tests/`에 결정적 모듈 테스트(또는 QA가 작성하도록 테스트 가능 구조 제공).

## 협업
- 각 모듈 완료 시 qa에 검증 요청(점진적). 데이터 모델 모순 발견 시 architect에 통지.
