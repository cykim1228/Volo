---
name: volo-build
description: Volo(프리미어용 AI 자동 자막 툴) 개발 오케스트레이터. 기획→설계→엔진 구현→앱 구현→통합검증을 5-에이전트 생성-검증 파이프라인으로 조율한다. Volo의 자막 기능 개발/구현/수정/확장 요청 시 사용. 트리거: "Volo 개발/구현", "자막 기능 추가", "엔진/앱 만들어", "기획하고 개발", "다시 실행/재실행/업데이트/수정/보완", "엔진만/앱만/세그멘테이션만 다시", "이전 결과 기반 개선", "QA 다시", "프리미어 자막 툴 개발".
---

# volo-build — Volo 개발 오케스트레이터

Volo 개발팀(planner·architect·engine-dev·app-dev·qa)을 하나의 워크플로우로 조율한다.
"누가 언제 어떤 순서로 협업하는가"를 정의한다(개별 "무엇을 어떻게"는 각 에이전트의 스킬이 담당).

## 실행 모드
**생성-검증 파이프라인** (의존 순차 + QA 점진 검증). 실행은 다음 중 택:
- **에이전트 팀**(기본): TeamCreate로 팀 구성, TaskCreate로 작업 분배, 팀원이 SendMessage로 자체 조율.
- **Workflow/서브에이전트**(결정적 제어가 필요할 때): 단계별 Agent 호출, 각 에이전트는 자기 스킬 파일을 읽고 수행. 각 Agent 호출에 `model: "opus"`, 코드 에이전트는 `agentType` 매핑(planner/architect/engine-dev/app-dev/qa).

모든 에이전트는 `model: "opus"`. 중간 산출물은 `_workspace/`, 코드는 실제 디렉토리.

## Phase 0: 컨텍스트 확인 (반드시 먼저)
1. `_workspace/`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, `volo_engine/` 존재 확인.
2. 실행 모드 판별:
   - 산출물 없음 → **초기 실행**(전체 파이프라인).
   - 산출물 있음 + 부분 수정 요청("엔진만", "세그멘테이션만", "QA 다시") → **부분 재실행**(해당 에이전트만 재호출, 의존 단계 영향 점검).
   - 산출물 있음 + 새 입력/방향 변경 → **새 실행**(기존 `_workspace/`를 `_workspace_prev/`로 이동 후 진행).

## 파이프라인 (초기 실행)
```
[1] planner   → docs/PRD.md
       │ (PRD 준비 신호)
[2] architect → docs/ARCHITECTURE.md, volo_engine/models.py, 스캐폴드
       │ (데이터 모델·인터페이스 확정)
[3] engine-dev → volo_engine/*, volo_cli/*   ─┐  (모듈별 완료 시마다)
[4] app-dev    → volo_app/*                   ─┤→ [5] qa: 점진 검증
       │ (engine API 안정 후 병렬 가능)         ─┘
[5] qa        → _workspace/QA_report.md, tests/*  (각 모듈 완료 직후 검증, 버그는 담당에 통지)
```
- [3]·[4]는 데이터 모델(models.py) 확정 후 병렬 가능. 단, app-dev는 engine-dev의 `pipeline` 공개 API가 안정되면 실연동.
- qa는 마지막 1회가 아니라 각 모듈 완료 직후 점진 검증(incremental). 버그 발견 → 담당 에이전트 1회 재시도 → 미해결 시 보고서에 누락 명시.

## 데이터 전달 프로토콜
- **태스크 기반**(조율): 의존 관계·진행상황을 TaskCreate/Update로 공유.
- **파일 기반**(산출물): 중간 산출물 `_workspace/{phase}_{agent}_{artifact}`, 최종 코드/문서는 실제 경로. `_workspace/`는 보존(감사 추적).
- **메시지 기반**(실시간): "PRD 준비됨", "모델 변경됨 영향 모듈 X", "버그 발견 위치 Y" 등 SendMessage.

## 에러 핸들링
- 에이전트 실패: 1회 재시도. 재실패 시 그 결과 없이 진행하고 산출물/보고서에 누락 명시.
- 상충 데이터(예: 데이터 모델 해석 차이): 삭제하지 않고 출처 병기, architect가 조정.
- 외부 의존 부재(ffmpeg/CUDA/모델): 엔진이 폴백 처리, qa는 "환경 미비로 실행 불가" 명시 후 정적 검증 대체.

## 후속 작업
- 부분 재실행: 해당 에이전트만 재호출하되, 데이터 모델이 바뀌면 영향 모듈(engine/app/qa)을 함께 갱신.
- 각 에이전트는 이전 산출물이 있으면 읽고 변경분만 수정(전체 재작성 금지).

## 테스트 시나리오
- **정상 흐름**: "Volo 개발 진행" → planner PRD → architect 설계+models.py → engine-dev 엔진+CLI → app-dev UI → qa가 segment/export pytest 실행·SRT 왕복 검증·수용 기준 판정 → 통합 보고.
- **부분 재실행**: "세그멘테이션 규칙만 한국어 16자로 다시" → Phase 0이 기존 산출물 감지 → engine-dev의 segment만 수정 → qa가 segment 회귀 검증.
- **에러 흐름**: engine-dev가 ffmpeg 경로 처리 누락 → qa가 폴백 경로 미비 발견 → engine-dev 통지 → 1회 재시도 수정 → qa 재검증.

## 완료 후
사용자에게 결과 요약 + 피드백 기회 제공("팀 구성·워크플로우·결과에서 바꿀 점이 있나요?"). 피드백은 유형별로 스킬/에이전트/오케스트레이터에 반영하고 CLAUDE.md 변경 이력에 기록.
