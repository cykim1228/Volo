---
name: volo-qa
description: Volo 통합 검증(QA) 방법론. 엔진↔앱/CLI 경계면 데이터 shape 교차 비교, SRT/VTT 포맷 유효성 검증, 결정적 모듈(segment/export/correct) pytest 실제 실행, PRD 수용 기준 대조. qa 에이전트가 사용. "Volo 검증", "QA", "통합 테스트", "경계면 점검", "수용 기준 확인", "자막 출력 검증" 요청 시 사용.
---

# volo-qa — Volo 통합 검증

qa 에이전트(general-purpose 타입)가 따르는 검증 방법론. 핵심은 "존재 확인"이 아니라 **"경계면 교차 비교 + 실제 실행"**.

## 컨텍스트 확인 (먼저)
- 검증 대상 모듈과 `docs/PRD.md`(수용 기준), `docs/ARCHITECTURE.md`, `data-model.md`를 읽는다.
- 기존 `_workspace/QA_report.md`가 있으면 읽고 신규/수정 모듈만 추가 검증 + 회귀 점검.

## 검증 방법론
1. **경계면 교차 비교.** 한쪽만 보지 않는다. 예:
   - `export.py`의 SRT 출력 ↔ `models.py:Subtitle` 필드 ↔ `volo_app`/`volo_cli`의 호출 결과를 동시에 읽어 shape·타입·nullability 일치 확인.
   - `pipeline.run` 시그니처 ↔ CLI 인자 ↔ 앱 호출부.
2. **실제 실행.** 외부 의존 없는 결정적 모듈은 pytest로 실행해 통과 확인. 무거운 STT는 실행하지 않고, 의존성 주입 인터페이스 정확성 + 수동 검증 절차를 보고서에 기재.
3. **포맷 유효성.** 생성된 SRT/VTT를 파싱해 표준 준수 확인(아래 체크리스트).
4. **불변식 검증.** `data-model.md`의 불변식(겹침 없음/인덱스 연속/줄 길이 등)을 cue 목록에 대해 검사.
5. **수용 기준 대조.** PRD 각 수용 기준 → 충족/미충족/검증불가(이유) 판정표.

세부 점검 항목은 `references/boundary-checks.md` 참조.

## 점진적 QA
전체 완성 후 1회가 아니라, engine-dev/app-dev가 모듈을 완료할 때마다 즉시 검증한다. 새 모듈이 기존 통과 항목을 깨지 않았는지(회귀) 함께 본다.

## 보고
- `_workspace/QA_report.md`: 모듈별 결과 + 발견 버그(위치·재현·기대값) + 수용 기준 판정표.
- 버그는 담당 에이전트에게 직접 통지(생성-검증 분리: QA는 수정하지 않고 요청). 1회 재시도 후에도 미해결이면 보고서에 누락으로 명시.
- **사실대로.** 통과 가장 금지. 실패는 출력과 함께, 건너뛴 것은 건너뛰었다고.

## 산출 (테스트 코드)
- 결정적 모듈용 pytest를 `tests/`에 작성/보강(예: `test_segment.py`, `test_export.py`). 공통 헬퍼는 중복 작성 말고 `tests/conftest.py`로 모은다.
