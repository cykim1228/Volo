# Volo PRD — 프리미어 프로용 AI 자동 자막 생성 데스크톱 툴

> 단일 진실 원천: 데이터 모델은 `.claude/skills/volo-architecture/references/data-model.md`, 엔진 도메인 지식은 `.claude/skills/volo-engine-dev/references/subtitle-domain.md`. 본 PRD의 모든 자료형/계약/수용 기준은 이 두 문서와 정합해야 한다.
> 작성: planner · 최종: `docs/PRD.md` · 중간: `_workspace/01_planner_prd.md`(동일 내용)

---

## 1. 문제 · 타깃

### 1.1 누가
- **1차 타깃**: 한국어 콘텐츠를 다루는 **어도비 프리미어 프로 편집자** — 유튜버/크리에이터 편집 외주, 인터뷰·강연·다큐 편집자, 사내 영상팀.
- **2차 타깃**: 다국어 자막(번역)이 필요한 위 편집자, 자막 외주 작업자.

### 1.2 어떤 상황에서 무엇이 고통인가
| 고통 | 현재 수작업 | 시간 비용 |
|------|------------|-----------|
| 받아쓰기(전사) | 영상을 들으며 한 문장씩 타이핑 | 10분 영상에 1~2시간 |
| 타임코드 맞추기 | cue마다 IN/OUT 점을 손으로 찍음 | 전사만큼 추가 |
| 줄바꿈/길이 조정 | 한 줄이 너무 길거나 화면을 벗어나지 않게 수동 분할 | cue 수에 비례 |
| 표시시간(가독성) | 너무 빨리 지나가는 자막을 일일이 늘림(CPS 감각에 의존) | 반복 노동 |
| 고유명사·전문용어 오타 | 받아쓰기·STT 오인식을 전체 훑으며 교정 | 누락 잦음 |
| 다국어 | 번역가에게 별도 의뢰 후 타임코드 재정렬 | 외부 비용·왕복 |

### 1.3 프리미어 기본 "음성을 텍스트로" 대비 Volo의 차별점
- **로컬·무비용 STT**: faster-whisper 로컬 추론. API 비용 0, 영상 외부 업로드 없음(프라이버시), 오프라인 가능.
- **한국어 정확도**: `large-v3` 기본 + 단어 타임스탬프로 타이밍 정밀.
- **부가가치 4종**: ① 한국어 교정 + 글로서리(고유명사 강제 교정) ② CPS/줄길이 기반 줄바꿈·타이밍 최적화 ③ 번역/다국어 동시 출력 ④ 스타일 프리셋. 프리미어 기본 자동자막은 ②③④와 글로서리 강제 교정을 제공하지 않는다.
- **표준 산출물**: `.srt`/`.vtt`로 내보내 프리미어 캡션 트랙에 그대로 임포트 → 기존 워크플로 비파괴.

---

## 2. 핵심 사용자 플로우

```
[영상 투입] → [옵션 설정] → [생성(파이프라인)] → [미리보기/편집] → [내보내기] → [프리미어 임포트]
```

| 단계 | 입력 | 처리 | 결과 |
|------|------|------|------|
| 1. 투입 | 영상/오디오 파일 경로(mp4, mov, mkv, wav …) | 파일 유효성 확인 | 처리 대상 확정 |
| 2. 옵션 | `TranscribeOptions`(모델/언어/device), `SegmentRules`(CPS·줄길이), 글로서리, 번역 대상 언어, 스타일 프리셋 | 기본값 + 사용자 조정 | 실행 파라미터 |
| 3. 생성 | 위 옵션 | extract_audio → transcribe → (correct) → segment → (translate) → (apply_style) | `list[Subtitle]` |
| 4. 미리보기/편집 (Phase 2 UI) | `list[Subtitle]` | cue 텍스트/타임/줄바꿈 수동 조정 | 수정된 `list[Subtitle]` |
| 5. 내보내기 | `list[Subtitle]`, 포맷(srt/vtt) | export | `name.srt`(+ 다국어 시 `name.ko.srt`/`name.en.srt`, 스타일 시 `name.style.json`) |
| 6. 임포트 | `.srt` | 프리미어 파일→가져오기 / 캡션 패널 | 캡션 트랙 생성 |

**MVP의 핵심 가치 경로(P0)**: 영상 → ffmpeg 오디오 추출 → faster-whisper 전사(단어 타임스탬프) → CPS/줄길이 세그멘테이션 → SRT 내보내기 → **CLI로 한 번에 동작**. (4단계 UI/편집은 Phase 2.)

---

## 3. 기능 목록 (우선순위 표)

우선순위: **P0**=핵심 가치 경로(없으면 제품 아님), **P1**=강한 부가가치, **P2**=있으면 좋음.
단계: **MVP / P2(Phase 2) / P3(Phase 3)**.

| 기능 | 설명 | 없애는 수작업 | 단계 | 우선순위 |
|------|------|----------------|------|----------|
| F1 오디오 추출 | ffmpeg로 영상→16kHz mono WAV | (전처리 자동화) | MVP | P0 |
| F2 STT 전사 | faster-whisper 로컬 추론, 단어 타임스탬프, device 자동감지 | 받아쓰기 + 타임코드 찍기 | MVP | P0 |
| F3 세그멘테이션 | 단어 타임스탬프 → CPS/줄길이 규칙으로 cue 재구성 | 줄바꿈·표시시간·cue 분할 수동 조정 | MVP | P0 |
| F4 SRT 내보내기 | 표준 SRT 파일 출력 | 자막 파일 수동 포맷팅 | MVP | P0 |
| F5 CLI | 단일 명령으로 F1~F4 실행 + 진행률 | 도구 간 수동 연결 | MVP | P0 |
| F6 한국어 교정 + 글로서리 | 글로서리 강제 치환 + 경량 규칙 교정(타임스탬프 보존) | 고유명사/오타 전수 교정 | MVP* / P2 | P1 |
| F7 VTT 내보내기 | WEBVTT 포맷 출력 | 포맷 변환 | P2 | P1 |
| F8 데스크톱 UI(미리보기/편집) | 파일 투입·옵션·진행률·cue 미리보기·간단 편집 | 결과 확인·미세 수정 환경 | P2 | P1 |
| F9 스타일 프리셋 | 프리셋(JSON) 보존 + export 시 사이드카(`*.style.json`) + 프리미어 적용 가이드 | 캡션 스타일 수동 설정 | P2 | P2 |
| F10 번역/다국어 동시 출력 | cue별 번역, 언어별 SRT 분리 출력 | 번역 의뢰·타임코드 재정렬 | P3 | P1 |
| F11 배치 처리 | 다수 파일 일괄 처리 | 파일마다 반복 실행 | P3 | P2 |
| F12 화자 분리 | 화자별 라벨(선택) | 화자 구분 수동 표기 | P3 | P2 |

\* F6은 **글로서리 강제 치환(결정적)** 만 MVP에 포함(STT 오인식 고유명사 교정은 핵심 가치에 직결). 맞춤법/띄어쓰기 고급 교정은 P2.

---

## 4. 기능별 요구사항

### F1 — 오디오 추출 (MVP / P0)
- 입력 `video_path: str` → 출력 `wav_path: str`. (data-model 계약 `extract_audio`.)
- 명령: `ffmpeg -i <video> -vn -ac 1 -ar 16000 -c:a pcm_s16le -y <out.wav>` (16kHz mono PCM, Whisper 선호 포맷).
- ffmpeg 바이너리: 시스템 PATH 우선 → 없으면 `imageio_ffmpeg.get_ffmpeg_exe()` 폴백 → 둘 다 없으면 설치 안내 메시지.
- WAV는 `tempfile` 임시 디렉토리에 생성, 처리 완료 시 정리.
- 입력이 이미 16kHz mono WAV면 변환 생략 가능(선택 최적화, 정합성 우선).

### F2 — STT 전사 (MVP / P0)
- 입력 `wav_path`, `TranscribeOptions` → 출력 `Transcript`. (계약 `transcribe`.)
- 모델 로딩: `WhisperModel(model_size, device, compute_type)`. 기본 `model_size="large-v3"`, `language="ko"`(None이면 자동감지).
- **device/compute_type 자동 선택**(`device="auto"`): CUDA 가능 → `cuda`/`float16`, 아니면 `cpu`/`int8`.
- 전사 호출: `word_timestamps=True`, `vad_filter=True`, `beam_size=5`. segment의 `.words`로 `Word(text,start,end,prob)` 채움.
- `segments`는 제너레이터 → 순회하며 `info.duration` 대비 `segment.end` 비율로 진행률 산출.
- 결과를 `Transcript(language, duration, segments: list[Segment])`로 조립. 각 `Segment`는 `index,start,end,text,words,lang`.
- **의존성 주입**: `transcribe(wav_path, opts, model=None)` — 테스트 시 가짜 모델 주입 가능(추론 자체는 테스트 안 함, 모킹 금지 원칙은 실제 호출 경로에 적용).
- 모델 최초 1회 자동 다운로드·캐시(`~/.cache/huggingface`). 실패 시 네트워크/경로 안내.

### F3 — 세그멘테이션 (MVP / P0)
- 입력 `Transcript`, `SegmentRules` → 출력 `list[Subtitle]`. (계약 `segment`.) 결정적 함수, 외부 의존 없음.
- 기본 규칙(`SegmentRules`): `max_chars_per_line=20`, `max_lines=2`, `max_cps=17.0`, `min_duration=1.0`, `max_duration=7.0`, `min_gap=0.08`.
- 절차(subtitle-domain §4):
  1. **단어 타임스탬프 기반 재구성**(가능하면 segment 무시, `words` 시퀀스 사용).
  2. **누적 → 분할**: 누적 글자수 > `max_chars_per_line*max_lines`, 누적 표시시간 > `max_duration`, 문장부호/종결 경계, 큰 침묵 간격 중 하나 위반 직전 cue 분할.
  3. **줄 배분**: 1~2줄, 각 줄 ≤ `max_chars_per_line`, 어절(공백) 경계 분할, 두 줄 균형, 조사·어미 고아 회피.
  4. **타이밍 보정**: `duration < min_duration`이면 다음 cue 전까지 end 연장; CPS > `max_cps`이면 표시시간 연장 또는 cue 분할; 겹침 제거 `next.start = max(next.start, prev.end + min_gap)`.
  5. **인덱스 재부여**: 1부터 연속.
- 모든 `Subtitle`은 data-model 불변식을 만족해야 한다(§5 수용 기준).

### F4 — SRT 내보내기 (MVP / P0)
- 입력 `list[Subtitle]`, `fmt="srt"`, `out_path` → 출력 `out_path`. (계약 `export`.)
- 포맷: `index`(1부터) → `HH:MM:SS,mmm --> HH:MM:SS,mmm`(쉼표, 밀리초 3자리) → `lines`(줄바꿈) → **빈 줄**로 cue 구분.
- 초→타임코드 변환은 export 시에만 수행(내부는 `float` 초).
- UTF-8(기본 BOM 없음, 호환용 BOM 옵션 제공 가능). 줄바꿈 `\n` 또는 `\r\n`.

### F5 — CLI (MVP / P0)
- 단일 명령으로 F1→F2→(F6 글로서리)→F3→F4 실행. 엔진(`volo_engine`) 호출만, 자체 로직 금지.
- 인자: 입력 파일(필수), `--model`, `--lang`, `--device`, `--max-cps`, `--max-chars`, `--glossary <json>`, `--out <path>`, `--format srt|vtt`.
- 진행률을 표준 출력에 표시(전사 단계 비율). 종료 코드: 성공 0, 실패 비0 + 원인 메시지.
- ffmpeg/모델 부재 등 환경 오류는 사용자 친화적 안내로 출력(스택트레이스 그대로 노출 금지).

### F6 — 한국어 교정 + 글로서리 (글로서리 MVP / 고급 교정 P2 / P1)
- 입력 `Transcript`, `glossary: dict[str,str]` → 출력 `Transcript`(텍스트만 수정, **타임스탬프 보존**). (계약 `correct`.)
- **글로서리 치환(MVP, 결정적·우선)**: `{잘못된표기: 올바른표기}` 매핑을 segment 텍스트에 적용. 대소문자/띄어쓰기 변형 고려. 고유명사·브랜드·전문용어 교정.
- **경량 규칙 교정(P2)**: 반복 공백 정리, 문장부호 정규화, 흔한 구어 오인식 패턴.
- **고급 교정(P2, 선택 플러그인)**: 규칙 기반/LLM 한국어 교정기. MVP는 규칙 기반 동작 보장(외부 의존 강제 아님).
- 단어 분할 변경 시 word 정렬을 깨지 않도록 segment 텍스트 레벨에서 처리.

### F7 — VTT 내보내기 (P2 / P1)
- `WEBVTT` 헤더 + 타임코드 구분자 점(`.`): `HH:MM:SS.mmm --> HH:MM:SS.mmm`. 나머지는 SRT와 동일 cue 구조.

### F8 — 데스크톱 UI (P2 / P1)
- 파일 투입(드래그&드롭/선택), 옵션 설정, 진행률 표시, cue 목록 미리보기, 간단 편집(텍스트/타임/줄바꿈 수정), 내보내기.
- UI는 엔진 호출만. 편집 결과도 `list[Subtitle]` 자료형 유지. 모킹 금지(실제 파이프라인 연결).

### F9 — 스타일 프리셋 (P2 / P2)
- `StylePreset(name, font_family, font_size, primary_color, outline_color, position)` JSON을 `assets/presets/`에 저장. 기본: `default`(하단·흰색+검은 외곽선), `youtube`(굵게·하단), `interview`(상단).
- 입력 `list[Subtitle]`, `StylePreset` → 출력 `list[Subtitle]`(`style` 채움). (계약 `apply_style`.)
- SRT는 스타일 미지원 → export 시 사이드카 `name.style.json` 출력 + 프리미어 캡션 트랙 적용 가이드 제공. (번인/ASS/MOGRT는 P3+.)

### F10 — 번역/다국어 (P3 / P1)
- 입력 `list[Subtitle]`, `target_lang: str` → 출력 `list[Subtitle]`(`translation[target_lang]`에 줄 리스트 저장, **타임코드 보존**). (계약 `translate`.)
- 번역 백엔드는 교체 가능한 인터페이스 `translate_lines(lines, src, tgt) -> lines`. 번역 후 대상 언어 줄길이 규칙으로 재배분.
- 다국어 동시 출력 시 언어별 파일 분리: `name.ko.srt`, `name.en.srt`.

### F11 — 배치 처리 (P3 / P2)
- 디렉토리/파일 목록 입력, 파일별 동일 파이프라인 반복, 개별 실패가 전체를 중단시키지 않음(요약 리포트).

### F12 — 화자 분리 (P3 / P2, 선택)
- `Segment.speaker`/`Subtitle` 화자 라벨 채움. 선택 기능(기본 비활성).

---

## 5. 기능별 수용 기준 (검증 가능 — QA가 그대로 검증)

> 공통 데이터 불변식(모든 단계 산출 `list[Subtitle]`에 적용, data-model §불변식):
> (I1) `start < end`, (I2) 인접 cue `next.start >= prev.end`(겹침 금지), (I3) `index` 1부터 연속, (I4) `lines`는 1~2개·각 줄 길이 ≤ `max_chars_per_line`(단어 분할 불가 예외 허용), (I5) 모든 타임스탬프 ≥ 0 이고 `end ≤ Transcript.duration`.

### F1 오디오 추출
- AC1.1 임의의 mp4/mov 입력에 대해 16000Hz, mono, PCM s16le WAV가 생성된다(파일 헤더로 검증).
- AC1.2 시스템 PATH에 ffmpeg가 없으면 `imageio-ffmpeg` 번들 바이너리로 성공한다.
- AC1.3 ffmpeg를 어느 경로로도 찾지 못하면 비0 종료 + "ffmpeg 설치/경로 안내" 메시지를 출력한다(스택트레이스 아님).
- AC1.4 처리 완료 후 임시 WAV가 정리된다(임시 디렉토리에 잔존 없음).

### F2 STT 전사
- AC2.1 한국어 영상 입력 시 반환 `Transcript.language == "ko"`(또는 자동감지 결과), `duration > 0`, `segments` 비어있지 않음.
- AC2.2 `word_timestamps=True`로 각 `Segment.words`가 채워지고, 모든 `Word`에 `0 <= prob <= 1`, `start <= end`.
- AC2.3 `device="auto"`에서 CUDA 가용 시 GPU 경로, 비가용 시 CPU(`int8`) 경로로 **예외 없이** 완주한다(GPU 없는 머신에서도 성공).
- AC2.4 `transcribe(wav, opts, model=<가짜모델>)`로 호출 시 주입 모델이 사용된다(의존성 주입 검증, 실제 추론 미수행).
- AC2.5 전사 중 진행률 값이 0→1 범위에서 단조 증가한다(`info.duration` 기준).

### F3 세그멘테이션
- AC3.1 출력 `list[Subtitle]`이 불변식 I1~I5를 모두 만족한다.
- AC3.2 어떤 cue의 CPS(`총 글자수 / (end-start)`)도 `max_cps`를 초과하지 않는다(텍스트가 길어 분할 불가한 단일 어절 예외는 리포트).
- AC3.3 모든 cue의 `min_duration <= (end-start) <= max_duration`(보정 후).
- AC3.4 각 줄은 어절(공백) 경계에서 분할되어 조사/어미 단독 고아 줄이 없다(테스트 케이스 셋으로 검증).
- AC3.5 동일 입력 `Transcript`+`SegmentRules`에 대해 출력이 **결정적**(재실행 시 동일)이다.

### F4 SRT 내보내기
- AC4.1 출력 `.srt`가 표준 구조를 만족한다: `index` 줄 → `HH:MM:SS,mmm --> HH:MM:SS,mmm` → 1~2 텍스트 줄 → 빈 줄.
- AC4.2 타임코드는 쉼표 구분 + 밀리초 3자리이며, 초→타임코드 변환이 라운드트립 일치(±1ms)한다.
- AC4.3 파일이 UTF-8로 인코딩되고(기본 BOM 없음), 표준 SRT 파서로 재파싱 시 cue 수/타임/텍스트가 보존된다.
- AC4.4 인덱스가 1부터 연속이고 cue 순서가 시간 오름차순이다.

### F5 CLI
- AC5.1 `volo <input.mp4> --out out.srt` 한 명령으로 F1→F2→F3→F4가 실행되어 `out.srt`가 생성된다(엔드투엔드).
- AC5.2 10분 내외 한국어 영상에서 산출 SRT가 I1~I5 + AC4.* 를 만족한다.
- AC5.3 잘못된 입력 경로/미지원 포맷/환경 부재 시 비0 종료 + 명확한 한 줄 원인 메시지(스택트레이스 비노출).
- AC5.4 `--glossary g.json` 제공 시 글로서리 매핑 표기가 출력 자막에 반영된다.
- AC5.5 `--max-cps`, `--max-chars` 등 옵션이 세그멘테이션 결과에 반영된다(값 변경 시 cue 분할 양상 변화).

### F6 교정 + 글로서리
- AC6.1 글로서리 `{"파이선":"파이썬"}` 적용 시 전사 텍스트의 해당 표기가 모두 치환되고, **타임스탬프가 변경되지 않는다**.
- AC6.2 글로서리는 띄어쓰기/대소문자 변형도 매칭한다(정의된 케이스 셋 기준).
- AC6.3 교정 후 `Transcript`의 segment/word 개수·시간이 보존된다(텍스트만 변경).

### F7 VTT
- AC7.1 출력이 `WEBVTT` 헤더로 시작하고 타임코드 구분자가 점(`.`)이며 밀리초 3자리다.
- AC7.2 동일 `list[Subtitle]`에서 SRT와 VTT의 cue 수/타임/텍스트가 일치한다.

### F8 데스크톱 UI
- AC8.1 파일 투입→생성→내보내기 전 과정이 UI에서 동작하고, 결과 SRT가 CLI 산출물과 동일 불변식을 만족한다.
- AC8.2 cue 편집(텍스트/타임 수정) 후 내보낸 SRT에 편집 내용이 반영된다.
- AC8.3 진행률이 UI에 표시된다.

### F9 스타일 프리셋
- AC9.1 프리셋 적용 시 각 `Subtitle.style`이 프리셋 이름으로 채워진다.
- AC9.2 export 시 `name.style.json` 사이드카가 함께 생성되고 프리셋 속성을 담는다.

### F10 번역/다국어
- AC10.1 번역 후 각 `Subtitle.translation[tgt]`가 채워지고 **원본 타임코드가 보존**된다.
- AC10.2 다국어 출력 시 `name.ko.srt`, `name.en.srt`가 각각 생성되고 각 파일이 AC4.* 를 만족한다.
- AC10.3 번역 백엔드를 가짜 구현으로 주입해도 인터페이스(`translate_lines`)로 동작한다.

### F11 배치
- AC11.1 다수 파일 입력 시 각 파일별 SRT가 생성되고, 한 파일 실패가 나머지 처리를 막지 않으며 요약 리포트가 출력된다.

### F12 화자 분리
- AC12.1 (선택 활성 시) cue/segment에 화자 라벨이 채워지고 SRT 출력에 화자 표기 규칙이 일관 적용된다.

---

## 6. 비목표 (이번에 하지 않는 것)

- **실시간/라이브 자막**: 스트리밍 중 실시간 캡션은 대상 아님(오프라인 파일 처리만).
- **영상 편집 기능**: 컷 편집·트랜지션·렌더링 등 NLE 기능 없음(프리미어가 담당).
- **클라우드/협업·계정 시스템**: 서버 업로드, 멀티유저 협업, 로그인. 로컬 단독 동작이 원칙.
- **번인(하드섭) 영상 출력 / MOGRT / ASS 고급 스타일**: Phase 3+ 검토. MVP~P2는 자막 파일 + 스타일 사이드카까지.
- **클라우드 STT/번역 API 의존**: 기본 경로는 로컬. (번역 백엔드 LLM/API는 교체형 옵션이며 핵심 경로 강제 아님.)
- **프리미어 패널 플러그인(CEP/UXP) 내장**: 본 버전은 독립 앱 + 파일 임포트. 패널 통합은 향후 검토.
- **자막 자동 의미 요약/하이라이트 생성**: 전사·교정·세그멘테이션·번역에 집중.

---

## 7. 용어 정의

- **STT** (Speech-to-Text): 음성을 텍스트로 변환하는 전사.
- **faster-whisper**: Whisper STT 모델의 고속 로컬 추론 구현(CTranslate2 기반). 본 제품의 전사 엔진.
- **단어 타임스탬프(word timestamps)**: 단어별 시작/끝 시각. 정밀 타이밍·세그멘테이션의 기반.
- **Segment**: Whisper 원시 전사 단위(문장 단위, 세그멘테이션 전). data-model `Segment`.
- **Subtitle / cue**: 화면에 한 번에 표시되는 자막 단위(1~2줄). data-model `Subtitle`.
- **세그멘테이션(segmentation)**: 원시 `Transcript`를 가독성 규칙에 맞는 `Subtitle` cue들로 재구성하는 과정.
- **CPS** (Characters Per Second): 초당 글자수. 자막 가독성 핵심 지표. 한국어 권장 ≤ 12~17.
- **줄 길이(max_chars_per_line)**: 한 줄 최대 글자수. 한국어 권장 16~20자.
- **표시시간(duration)**: cue가 화면에 떠 있는 시간(end−start). 권장 1~7초.
- **cue 간 간격(min_gap)**: 인접 cue 사이 최소 공백(권장 ~80ms, 깜빡임 방지).
- **고아(orphan)**: 조사/어미만 다음 줄로 떨어진 부자연스러운 줄바꿈. 회피 대상.
- **글로서리(glossary)**: `{잘못된표기: 올바른표기}` 사용자 사전. 고유명사·전문용어 강제 교정.
- **SRT** (SubRip): 가장 보편적 자막 포맷. 인덱스+타임코드(`,` 밀리초)+텍스트+빈 줄. 프리미어 직접 임포트.
- **VTT** (WebVTT): 웹 표준 자막. `WEBVTT` 헤더 + 타임코드(`.` 밀리초).
- **스타일 프리셋(StylePreset)**: 폰트/색/위치 묶음. SRT 미지원이라 사이드카/가이드로 제공.
- **번인(burn-in / 하드섭)**: 자막을 영상 픽셀에 직접 입히는 것. 본 버전 비목표(P3+).
- **device/compute_type**: 추론 하드웨어·정밀도. `auto`=CUDA 가용 시 GPU/float16, 아니면 CPU/int8.

---

## 8. OPEN QUESTIONS (결정 필요 — architect/오케스트레이터에 전달)

- OQ1. **데스크톱 UI 스택**: Electron/Tauri/PySide 등 — 엔진(Python)과의 연결 방식 결정 필요(architect). PRD는 "엔진 호출, `list[Subtitle]` 유지"만 규정.
- OQ2. **고급 한국어 교정기**(P2)의 구체 백엔드(규칙 기반 vs LLM vs 외부 교정 API)와 오프라인 동작 보장 여부.
- OQ3. **번역 백엔드**(P3) 기본 구현체 선정(로컬 모델 vs 외부 API)과 비용/오프라인 정책.
- OQ4. SRT 출력 줄바꿈 기본값(`\n` vs `\r\n`)과 BOM 기본값 — 프리미어 임포트 호환 실측 필요(qa).
- OQ5. 패키징/배포 형태(설치형 vs 포터블)와 모델 가중치 동봉 여부(`large-v3` 용량 고려).

---

## 9. 변경 메모
- 2026-06-19 · 초기 작성 · planner. data-model.md / subtitle-domain.md와 정합. MVP=F1~F5(+F6 글로서리 치환).
