# Volo 경계면 검증 체크리스트

QA가 모듈 검증 시 사용하는 구체 점검 항목. 각 항목은 두 개 이상의 파일을 동시에 읽고 비교한다.

## A. 데이터 모델 정합성
- [ ] 각 파이프라인 단계의 입력/출력 타입이 `models.py` 자료형과 정확히 일치(필드명·타입·nullability).
- [ ] `Subtitle.lines`가 항상 list[str](문자열 단일값 아님), `translation`은 dict 또는 None.
- [ ] 타임스탬프가 전 구간 float 초 단위(어떤 단계도 ms 정수로 바꾸지 않음 — SRT 포맷 시점 제외).

## B. SRT 포맷 유효성 (export 출력 파싱)
- [ ] cue가 빈 줄로 구분됨.
- [ ] 인덱스가 1부터 연속 정수.
- [ ] 타임코드 형식 `HH:MM:SS,mmm --> HH:MM:SS,mmm`(쉼표, 밀리초 3자리, 0패딩).
- [ ] `start < end`, 인접 cue `next.start >= prev.end`(겹침 없음).
- [ ] UTF-8로 읽힘, 한글 깨지지 않음.
- [ ] 각 cue 줄 수 1~2.

## C. VTT 포맷 (출력 시)
- [ ] 파일이 `WEBVTT`로 시작.
- [ ] 타임코드 구분자가 점(`.`).

## D. 세그멘테이션 규칙 (segment 출력)
- [ ] 각 줄 길이 ≤ `SegmentRules.max_chars_per_line`(불가피한 단어 분할 예외만 허용, 보고서에 기록).
- [ ] cue 표시시간 `min_duration` ~ `max_duration` 범위.
- [ ] CPS ≤ `max_cps`(초과 cue는 목록화).
- [ ] 인접 cue 간격 ≥ `min_gap`.

## E. 인터페이스 정합성 (CLI/앱 ↔ 엔진)
- [ ] `pipeline.run(...)` 시그니처 ↔ CLI 인자 파서 ↔ 앱 호출부의 인자/순서/기본값 일치.
- [ ] `progress_cb` 시그니처(`(stage, ratio)`)를 앱/CLI가 올바르게 구독.
- [ ] 엔진이 던지는 예외 타입을 앱/CLI가 잡아 사용자 메시지로 변환.

## F. 폴백·에러 경로
- [ ] ffmpeg 미설치 시 명확한 메시지(조용한 실패 아님).
- [ ] CUDA 없을 때 CPU 폴백 동작.
- [ ] 모델 다운로드 실패 시 안내.

## G. 수용 기준 매핑
- [ ] PRD의 각 수용 기준 → 충족/미충족/검증불가. 검증불가는 이유(예: 실제 영상 필요)와 수동 검증 절차 기재.

## 실행 방법
- 결정적 모듈: `python -m pytest tests/ -q` 실제 실행, 결과 첨부.
- 포맷 검증: 샘플 `list[Subtitle]`를 만들어 export → 파일을 다시 파싱해 위 항목 검사(왕복 테스트).
- 환경 미비로 실행 불가 시: 원인 명시 + 정적 검증으로 대체 + 보고서에 "미실행" 표기.
