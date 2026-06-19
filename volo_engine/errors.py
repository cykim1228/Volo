"""Volo 엔진 공용 예외.

엔진의 모든 도메인 오류는 :class:`VoloError` 를 상속한다. CLI/앱은 이 타입을 잡아
사용자 친화적 메시지(스택트레이스 비노출)로 변환한다.

이 모듈은 stdlib만 사용하며 무거운 의존성을 import 하지 않는다.
"""

from __future__ import annotations

__all__ = [
    "VoloError",
    "VoloDependencyError",
    "VoloInputError",
    "VoloAudioError",
    "VoloTranscribeError",
    "VoloModelError",
    "VoloExportError",
]


class VoloError(Exception):
    """모든 Volo 엔진 오류의 베이스 클래스.

    Attributes:
        message: 사람이 읽을 한 줄 원인 메시지(CLI/UI에 그대로 노출 가능).
        hint: 해결 안내(설치/경로 등). 선택.
    """

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)

    def user_message(self) -> str:
        """CLI/UI에 표시할 한 줄(또는 두 줄) 메시지를 만든다.

        스택트레이스 대신 이 문자열을 출력한다(PRD AC1.3 / AC5.3).
        """
        if self.hint:
            return f"{self.message}\n  → {self.hint}"
        return self.message


class VoloDependencyError(VoloError):
    """외부 의존성(ffmpeg, faster-whisper, 모델 가중치 등)이 없거나 사용 불가."""


class VoloInputError(VoloError):
    """입력 파일/인자 오류(존재하지 않는 경로, 미지원 포맷, 잘못된 옵션 값)."""


class VoloAudioError(VoloError):
    """오디오 추출(extract_audio) 단계 실패."""


class VoloTranscribeError(VoloError):
    """전사(transcribe) 단계 실패."""


class VoloModelError(VoloDependencyError):
    """STT 모델 로딩/다운로드 실패(네트워크·캐시·디바이스 문제)."""


class VoloExportError(VoloError):
    """자막 내보내기(export) 단계 실패(쓰기 권한, 미지원 포맷 등)."""
