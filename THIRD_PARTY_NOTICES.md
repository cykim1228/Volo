# Third-Party Notices — Volo

Volo 본체는 [MIT 라이선스](LICENSE)로 배포됩니다. 다만 Volo는 아래 오픈소스에 의존하며,
각 구성요소는 **자체 라이선스**를 그대로 따릅니다. 공개·재배포 시 이 고지를 함께 포함하세요.

## 런타임 의존성

| 구성요소 | 용도 | 라이선스 | 비고 |
|---|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | STT(음성→텍스트) | MIT | CTranslate2 기반(torch 불필요) |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | 추론 엔진 | MIT | faster-whisper 의존 |
| [PyAV (`av`)](https://github.com/PyAV-Org/PyAV) | 미디어 디코딩 | BSD-3-Clause | 휠에 FFmpeg 동봉(아래 FFmpeg 항 참조) |
| [onnxruntime](https://github.com/microsoft/onnxruntime) | VAD 등 | MIT | faster-whisper 의존 |
| [tokenizers](https://github.com/huggingface/tokenizers) | 토크나이저 | Apache-2.0 | faster-whisper 의존 |
| [huggingface-hub](https://github.com/huggingface/huggingface_hub) | 모델 다운로드 | Apache-2.0 | faster-whisper 의존 |
| [tqdm](https://github.com/tqdm/tqdm) | 진행률 | MPL-2.0 + MIT | |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | ffmpeg 폴백 바이너리 제공 | BSD-2-Clause (래퍼) | 동봉 FFmpeg는 아래 참조 |
| [PySide6 / Qt for Python](https://wiki.qt.io/Qt_for_Python) | 데스크톱 UI(선택, `[app]`) | **LGPL-3.0** (또는 GPL/상용) | 아래 "LGPL 준수" 참조 |

## 모델 가중치

- **Whisper 모델**(`large-v3`, `medium` 등): OpenAI Whisper는 **MIT**, faster-whisper용
  CTranslate2 변환본(예: Hugging Face `Systran/faster-whisper-*`)도 **MIT**로 배포됩니다.
- 가중치는 Volo 저장소에 **포함하지 않습니다.** 최초 실행 시 사용자 PC로 자동 다운로드되어
  캐시됩니다(수 GB). 저장소를 가볍게 유지하고 모델 라이선스/배포 부담을 지지 않기 위함입니다.

## FFmpeg

`imageio-ffmpeg`와 `PyAV`는 각각 FFmpeg 바이너리를 내려받거나 동봉합니다.

- **FFmpeg 자체 라이선스: LGPL-2.1+** (기본 빌드). 단, `--enable-gpl` 옵션으로 빌드된
  바이너리는 **GPL**이 됩니다. 동봉 빌드의 정확한 라이선스는 배포 전 해당 바이너리의 빌드
  구성을 확인하세요. ([FFmpeg License & Legal](https://www.ffmpeg.org/legal.html))
- 일부 코덱은 특허 대상일 수 있습니다. Volo는 **오디오 디코딩**만 사용하지만, 상용 재배포
  시에는 코덱/특허 정책을 검토하세요.
- 안전한 배포 전략: **시스템에 설치된 FFmpeg 사용을 권장**하거나, 동봉할 경우 LGPL 빌드를
  명시적으로 선택하세요.

## LGPL 준수 (PySide6 / FFmpeg) — 배포 시 주의

소스 공개(이 GitHub 저장소)만으로는 추가 의무가 거의 없습니다. **단일 실행파일(.exe)로 번들
배포**할 때 LGPL 의무가 발생합니다:

- LGPL 라이브러리(Qt/PySide6, FFmpeg)는 **정적 링크하지 말고**, 사용자가 해당 라이브러리를
  교체할 수 있어야 합니다. PyInstaller `onedir` 모드는 Qt를 별도 DLL로 배치하므로 보통 이
  요건을 만족합니다(반대로 단일 `--onefile` 정적 번들은 주의).
- 배포물에 각 라이브러리의 **라이선스 전문**과 출처, 그리고 재링크/교체 방법 안내를 포함하세요.
- 상용으로 Qt를 정적 링크하거나 LGPL 의무를 피하고 싶다면 Qt **상용 라이선스**가 필요합니다.

> 요약: **MIT로 공개 + 소스 배포는 문제없음.** `.exe` 번들 배포 단계에서 위 LGPL 체크리스트를
> 적용하면 됩니다. 본 문서는 정보 제공용이며 법률 자문이 아닙니다 — 상용 배포 전 검토를 권장합니다.
