# Volo 자막 도메인 지식

엔진 구현에 필요한 도메인 지식 모음. 필요한 절만 읽는다.

## 목차
1. [ffmpeg 오디오 추출](#1-ffmpeg-오디오-추출)
2. [faster-whisper 전사](#2-faster-whisper-전사)
3. [한국어 자막 관례 (CPS·줄 길이)](#3-한국어-자막-관례)
4. [세그멘테이션 알고리즘](#4-세그멘테이션-알고리즘)
5. [한국어 교정 + 글로서리](#5-한국어-교정--글로서리)
6. [번역](#6-번역)
7. [내보내기 포맷 (SRT/VTT/프리미어)](#7-내보내기-포맷)
8. [스타일 프리셋](#8-스타일-프리셋)

---

## 1. ffmpeg 오디오 추출
- Whisper 계열은 16kHz mono PCM을 선호. 영상에서 오디오만 뽑아 정규화한다.
- 명령 예: `ffmpeg -i <video> -vn [-af <filters>] -ac 1 -ar 16000 -c:a pcm_s16le -y <out.wav>`
- ffmpeg 바이너리는 시스템 PATH 우선, 없으면 `imageio-ffmpeg`의 번들 바이너리 경로(`imageio_ffmpeg.get_ffmpeg_exe()`)로 폴백. 미설치 시 사용자에게 설치 안내 메시지.
- 긴 영상은 임시 디렉토리(`tempfile`)에 WAV 생성 후 사용, 완료 시 정리.
- **전처리 필터(STT 정확도 향상, `build_audio_filters`)**: 실제 영상은 잡음·음량 편차로 인식률이 떨어진다. 기본 적용(옵션으로 끄기 가능):
  - `highpass=f=80` — 저주파 럼블 제거.
  - `afftdn=nf=-25` — FFT 광대역 잡음 감쇠(가벼운 강도).
  - `loudnorm=I=-16:TP=-1.5:LRA=11` — EBU R128 음량 정규화(작은 음성 보정).
  - 순서: denoise(highpass→afftdn) → normalize(loudnorm). 모두 ffmpeg 내장 필터(외부 모델 불필요). 깨끗한 녹음이면 꺼도 무방.

## 2. faster-whisper 전사
- 패키지: `faster-whisper`. 모델 로딩:
  ```python
  from faster_whisper import WhisperModel
  model = WhisperModel(model_size, device=device, compute_type=compute_type)
  ```
- **device/compute_type 자동 선택**: CUDA 사용 가능하면 `device="cuda", compute_type="float16"`, 아니면 `device="cpu", compute_type="int8"`. `device="auto"` 입력 시 이 로직으로 해석.
- 전사 호출:
  ```python
  segments, info = model.transcribe(
      wav_path, language="ko", word_timestamps=True,
      vad_filter=True,                 # 무음 구간 제거로 타임스탬프 안정화
      beam_size=5,
  )
  ```
  - `segments`는 **제너레이터**(지연 평가)다. 진행률을 계산하려면 `info.duration` 대비 각 segment의 `end`로 비율을 산출하며 순회한다.
  - 각 segment의 `.words`(word_timestamps=True일 때)에서 `Word(text,start,end,prob)`를 채운다.
- 모델 선택 가이드: `large-v3`가 한국어 정확도 최상(느림, VRAM↑). 빠른 처리는 `medium`/`large-v3-turbo`. 기본값 `large-v3`, 옵션으로 낮출 수 있게.
- 모델은 최초 1회 자동 다운로드되어 캐시된다. `WhisperModel(..., download_root=model_cache_dir())`로 캐시 경로(`VOLO_MODEL_CACHE`/`HF_HOME`)를 연결. 다운로드 실패 시 네트워크/경로 안내.
- **의존성 주입**: `transcribe(wav_path, opts, model=None)`처럼 모델 객체를 주입 가능하게 하여, 테스트에서 가짜 모델로 호출부를 검증할 수 있게 한다(추론 자체는 테스트 안 함).

### 한국어 품질 핵심 (환각·반복 억제 + 인식 힌트)
Whisper 한국어 자동자막의 품질을 좌우하는 디코딩 파라미터. `TranscribeOptions`로 노출하고 `model.transcribe(...)`에 전달한다:
- **`initial_prompt`** — 가장 큰 지렛대. 고유명사·브랜드명의 **올바른 표기**나 도메인 어휘를 넣으면 인식이 그 방향으로 유도된다. 글로서리의 "값(교정표기)"을 합쳐 자동 구성(파이프라인 `_build_initial_prompt`). 사후 치환(correct)보다 효과가 크다. 프롬프트는 마지막 ~224 토큰만 사용되므로 용어 수를 제한한다.
- **`condition_on_previous_text=False`** — 이전 구간 텍스트를 조건으로 쓰지 않음 → 반복 루프/환각 드리프트를 줄인다. 자막에 권장 기본.
- **`temperature` 폴백** `(0.0, 0.2, … 1.0)` — 낮은 온도 디코딩이 실패(아래 임계 위반)하면 단계적으로 온도를 올려 재시도.
- **`compression_ratio_threshold=2.4`** — 출력 압축비가 높으면(같은 말 반복 의심) 기각/폴백.
- **`log_prob_threshold=-1.0`** — 평균 로그확률이 낮으면(저신뢰) 기각/폴백.
- **`no_speech_threshold=0.6`** — 무음 확률이 높은 구간 제거(헛텍스트 방지).
- **`hallucination_silence_threshold=2.0`** — word_timestamps 사용 시, 긴 무음에서 생기는 환각 텍스트를 건너뜀.
- VAD(`vad_filter=True`)와 함께 쓰면 무음 구간 환각이 크게 줄어든다.
- 더 높은 한국어 정확도가 필요하면: 한국어 파인튜닝 Whisper 모델 사용, 또는 사후 교정에 PyKoSpacing/Kiwi(형태소) 결합(선택·플러그인).

## 3. 한국어 자막 관례
방송·OTT 한국어 자막의 가독성 기준(권장 기본값, `SegmentRules`로 조정):
- **한 줄 길이**: 한글 기준 약 16~20자. 너무 길면 시선 이동 부담.
- **최대 줄 수**: 2줄.
- **CPS(초당 글자수)**: 한국어는 대략 12~17 CPS 이하 권장. 상한 초과 시 표시시간을 늘리거나 cue를 분할.
- **표시시간**: 최소 ~1.0초(짧으면 못 읽음), 최대 ~7초.
- **cue 간 간격**: 최소 ~80ms(붙어 있으면 깜빡임).
- **줄바꿈 위치**: 의미 단위(구/절) 경계에서. 조사("을/를/이/가/은/는/에/에서"…)나 어미만 다음 줄로 떨어지는 고아(orphan) 금지. 가능하면 어절(공백) 경계에서 자른다.

## 4. 세그멘테이션 알고리즘
목표: Whisper의 원시 `Segment`(문장 단위, 길거나 들쭉날쭉)를 화면 표시에 맞는 `Subtitle` cue로 재구성.

권장 절차:
1. **단어 타임스탬프 기반 재구성.** 가능하면 segment를 무시하고 `words` 시퀀스로부터 cue를 만든다(타이밍이 정확).
2. **누적 → 분할.** 단어를 누적하며 다음 조건 중 하나라도 위반 직전이면 cue를 끊는다:
   - 누적 글자수 > `max_chars_per_line * max_lines`
   - 누적 표시시간(현재 단어 end − cue start) > `max_duration`
   - 문장부호(`. ? ! …` / 한국어 종결 어미 후 긴 휴지) 경계
   - 단어 간 침묵 간격이 큼(자연 분할점)
3. **줄 배분.** cue 텍스트를 1~2줄로 나눈다. `max_chars_per_line` 이하가 되도록 어절 경계에서 분할하고, 두 줄 길이를 균형 있게(상단이 약간 길거나 비슷하게). 조사·어미 고아 회피.
4. **타이밍 보정.**
   - `duration < min_duration`이면 다음 cue 시작 전까지 end를 늘려 보충.
   - CPS > `max_cps`이면 가능 범위에서 표시시간을 늘리거나, 텍스트가 길면 cue를 둘로 분할.
   - 인접 cue 겹침 제거: `next.start = max(next.start, prev.end + min_gap)`.
5. **인덱스 재부여.** 1부터 연속.

결정적 함수로 작성(입력 `Transcript`+`SegmentRules` → 출력 `list[Subtitle]`). 외부 의존 없음 → pytest로 불변식 검증.

## 5. 한국어 교정 + 글로서리
- **글로서리 치환(우선·결정적)**: 사용자가 제공한 `{잘못된표기: 올바른표기}` 또는 발음 유사어 매핑을 텍스트에 적용. 고유명사·브랜드명·전문용어 오인식 교정. 대소문자/띄어쓰기 변형 고려.
- **맞춤법·띄어쓰기**: 경량 규칙(반복 공백 정리, 문장부호 정규화, 흔한 구어 오인식 패턴) 우선. 더 높은 품질이 필요하면 외부 한국어 교정기(예: 규칙 기반/LLM)를 **선택적 플러그인**으로 두되 MVP는 규칙 기반으로 동작 보장.
- 교정은 타임스탬프를 보존한다(텍스트만 수정). 단어 분할이 바뀌면 word 정렬을 깨지 않도록 segment 텍스트 레벨에서 처리.

## 6. 번역
- 입력은 세그멘테이션된 `list[Subtitle]`(cue 단위). **cue별로 번역**하되 타임코드는 그대로 보존하고 `Subtitle.translation[target_lang]`에 줄 리스트로 저장.
- 번역 후 대상 언어의 줄 길이 규칙으로 다시 줄 배분(언어마다 길이 다름).
- 번역 백엔드는 교체 가능한 인터페이스(`translate_lines(lines, src, tgt) -> lines`). MVP는 인터페이스만 확정하고 구현 백엔드는 단계적으로(LLM/사전 API 등).
- 다국어 동시 출력 시 언어별 SRT 파일을 따로 내보낸다(`name.ko.srt`, `name.en.srt`).

## 7. 내보내기 포맷
### SRT (주력 — 프리미어가 직접 임포트)
```
1
00:00:01,000 --> 00:00:03,200
첫 번째 자막 줄
두 번째 자막 줄

2
00:00:03,300 --> 00:00:05,000
다음 자막
```
규칙: 인덱스(1부터) → 타임코드 `HH:MM:SS,mmm`(쉼표, 밀리초 3자리) → 줄들 → **빈 줄**로 cue 구분. UTF-8(BOM 없이; 일부 환경 호환 위해 BOM 옵션 제공 가능). 줄바꿈은 `\n` 또는 `\r\n`(프리미어는 둘 다 허용).

### VTT
```
WEBVTT

00:00:01.000 --> 00:00:03.200
첫 번째 자막
```
타임코드 구분자가 점(`.`)이고 파일 시작에 `WEBVTT` 헤더.

### 프리미어 임포트 메모
- 프리미어 프로는 `.srt`를 **캡션 트랙**으로 직접 임포트(파일 → 가져오기, 또는 캡션 패널). 스타일은 캡션 트랙 속성에서 조정.
- 스타일까지 파일로 넣고 싶으면 SRT는 스타일을 담지 못하므로, 스타일 정보는 별도(프리셋 문서/메타)로 제공하고 사용자가 캡션 트랙에 적용하도록 안내. (고급: MOGRT/자막 디자인은 Phase 3+.)

## 8. 스타일 프리셋
- `StylePreset`(font_family, font_size, primary_color, outline_color, position)을 JSON으로 `assets/presets/`에 저장.
- 기본 프리셋 예: `default`(하단, 흰색+검은 외곽선), `youtube`(굵게, 하단), `interview`(상단). 
- SRT는 스타일 미지원이므로 프리셋은 (a) 미리보기 렌더링, (b) 프리미어 적용 가이드, (c) 향후 번인/ASS 출력에 사용. MVP에서는 프리셋을 메타로 보존하고 export 시 사이드카(`name.style.json`)로 함께 출력.
