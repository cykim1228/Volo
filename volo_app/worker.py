"""volo_app.worker — 엔진 파이프라인을 백그라운드(QThread)에서 실행하는 워커.

무거운 추론(faster-whisper)·오디오 추출(ffmpeg)은 메인(UI) 스레드를 막으면 안 된다.
이 모듈은 :func:`volo_engine.pipeline.run` 을 **워커 스레드에서 호출만** 하고, 진행률·완료·
에러를 Qt 시그널로 메인 스레드에 전달한다. UI는 이 시그널만 구독해 위젯을 갱신한다.

엔진 분리 원칙
--------------
- 엔진 로직을 재구현하지 않는다. ``pipeline.run(video_path, options, progress_cb=...)`` 을 호출만 한다.
- ``progress_cb(stage, ratio)`` 콜백(워커 스레드에서 호출됨)을 Qt 시그널로 브리지해
  메인 스레드로 안전하게 넘긴다. Qt 시그널은 스레드 경계를 넘어 큐잉되므로
  UI 위젯을 워커 스레드에서 직접 만지지 않는다.

PySide6 미설치 환경
-------------------
이 모듈을 import 하는 것만으로 PySide6 설치를 강제하지 않도록, PySide6 import 실패 시
:data:`PYSIDE_AVAILABLE` 를 ``False`` 로 두고 가벼운 더미 베이스(:class:`_QtUnavailable`)를
사용한다. 실제 워커 사용 시에는 PySide6 가 필요하다(없으면 명확한 RuntimeError).
"""

from __future__ import annotations

from typing import Any

try:  # PySide6 가 없는 환경에서도 파일 자체는 import 가능해야 한다.
    from PySide6.QtCore import QObject, QThread, Signal

    PYSIDE_AVAILABLE = True
except Exception:  # pragma: no cover - PySide6 미설치 환경 폴백
    PYSIDE_AVAILABLE = False

    class _QtUnavailable:  # 최소 더미: 상속/시그널 자리만 채운다.
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(
                "PySide6 가 설치되어 있지 않습니다. UI/워커를 사용하려면 "
                "`pip install -e .[app]` 또는 `pip install PySide6` 로 설치하세요."
            )

    QObject = _QtUnavailable  # type: ignore[assignment,misc]
    QThread = _QtUnavailable  # type: ignore[assignment,misc]

    def Signal(*_args: Any, **_kwargs: Any) -> Any:  # type: ignore[misc]
        return None


# 단계 이름 → 사용자에게 보일 한국어 라벨(진행률 텍스트). pipeline 의 stage 문자열과 정합.
STAGE_LABELS: dict[str, str] = {
    "extract_audio": "오디오 추출 중",
    "transcribe": "전사 중",
    "correct": "교정 중",
    "segment": "자막 세그멘테이션 중",
    "translate": "번역 중",
    "style": "스타일 적용 중",
    "export": "내보내는 중",
}

# 단계별 전체 진행률 가중치(합 = 1.0). transcribe 가 가장 무겁다.
# pipeline.run 은 단계 내부 비율(0~1)만 주므로, 전체 막대 값은 워커가 누적 계산한다.
STAGE_WEIGHTS: dict[str, float] = {
    "extract_audio": 0.05,
    "transcribe": 0.70,
    "correct": 0.02,
    "segment": 0.05,
    "translate": 0.10,
    "style": 0.02,
    "export": 0.06,
}

# 전체 진행률 누적 시 단계 순서(앞 단계들의 가중치를 누적해 기준점으로 삼는다).
_STAGE_ORDER: tuple[str, ...] = (
    "extract_audio",
    "transcribe",
    "correct",
    "segment",
    "translate",
    "style",
    "export",
)


def _stage_base(stage: str) -> float:
    """주어진 단계의 시작 지점(앞선 단계들의 가중치 합)을 반환한다."""
    base = 0.0
    for name in _STAGE_ORDER:
        if name == stage:
            return base
        base += STAGE_WEIGHTS.get(name, 0.0)
    return base


def overall_ratio(stage: str, ratio: float) -> float:
    """단계 내부 비율(0~1)을 전체 막대 비율(0~1)로 변환한다.

    pipeline.run 의 ``progress_cb(stage, ratio)`` 는 *단계 내부* 진행도만 보고한다.
    전체 진행률 막대는 단계 가중치(:data:`STAGE_WEIGHTS`)로 누적해 계산한다.
    """
    ratio = max(0.0, min(1.0, ratio))
    base = _stage_base(stage)
    weight = STAGE_WEIGHTS.get(stage, 0.0)
    return max(0.0, min(1.0, base + weight * ratio))


# 모델 다운로드는 파이프라인 가중치 밖의 별도 0~100% 패스로 표시한다(최초 1회).
_DOWNLOAD_STAGE = "download"
_DOWNLOAD_LABEL = "모델 다운로드 중 (최초 1회)"


def format_progress(stage: str, ratio: float) -> tuple[str, int]:
    """진행률 콜백 입력을 (사용자 라벨, 0~100 정수)로 변환한다.

    ``download`` 단계는 가중치 밖의 자체 0~100% 패스로 표시하고(첫 실행 모델 다운로드),
    그 외 파이프라인 단계는 :data:`STAGE_WEIGHTS` 로 누적한 전체 비율을 쓴다.
    """
    if stage == _DOWNLOAD_STAGE:
        return _DOWNLOAD_LABEL, int(round(max(0.0, min(1.0, ratio)) * 100))
    label = STAGE_LABELS.get(stage, stage)
    return label, int(round(overall_ratio(stage, ratio) * 100))


class PipelineWorker(QObject):  # type: ignore[misc]
    """엔진 파이프라인을 실행하는 QThread 워커(QObject + moveToThread 패턴).

    사용법(메인 스레드)::

        thread = QThread()
        worker = PipelineWorker(video_path, options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(on_progress)      # (stage_label, percent_int)
        worker.finished.connect(on_finished)       # (result_dict)
        worker.failed.connect(on_failed)           # (user_message, detail)
        worker.done.connect(thread.quit)
        thread.start()

    시그널:
        progress(str, int): (사용자용 단계 라벨, 전체 진행률 0~100). UI 갱신용.
        finished(object): 성공 시 ``pipeline.run`` 의 반환 dict.
        failed(str, str): 실패 시 (사용자 메시지, 상세/타입). 다이얼로그 표시용.
        done(): 성공/실패 무관 종료 신호(스레드 정리용).
    """

    progress = Signal(str, int)
    finished = Signal(object)
    failed = Signal(str, str)
    done = Signal()

    def __init__(self, video_path: str, options: Any, parent: Any | None = None) -> None:
        super().__init__(parent)
        self._video_path = video_path
        self._options = options

    def run(self) -> None:
        """워커 스레드 진입점. 엔진을 호출하고 결과/에러를 시그널로 보고한다."""
        # 엔진 import 는 실행 시점에(무거운 의존성 지연). UI import 시 강제하지 않는다.
        try:
            from volo_engine import pipeline as pipeline_mod
        except Exception as exc:  # pragma: no cover - 엔진 미설치 등
            self.failed.emit(
                "volo_engine 을 불러올 수 없습니다.",
                f"{type(exc).__name__}: {exc}",
            )
            self.done.emit()
            return

        def progress_cb(stage: str, ratio: float) -> None:
            # 워커 스레드에서 호출됨 → Qt 시그널(큐 연결)로 메인 스레드에 전달.
            label, percent = format_progress(stage, ratio)
            self.progress.emit(label, percent)

        try:
            result = pipeline_mod.run(
                self._video_path,
                self._options,
                progress_cb=progress_cb,
            )
        except Exception as exc:  # VoloError 포함 모든 예외를 사용자 메시지로 변환.
            user_msg, detail = _format_exception(exc)
            self.failed.emit(user_msg, detail)
            self.done.emit()
            return

        self.progress.emit("완료", 100)
        self.finished.emit(result)
        self.done.emit()


def _format_exception(exc: BaseException) -> tuple[str, str]:
    """엔진 예외를 (사용자 메시지, 상세) 로 변환한다.

    :class:`volo_engine.errors.VoloError` 는 ``user_message()`` 로 친절한 메시지를 만든다
    (스택트레이스 비노출, PRD AC1.3/AC5.3). 그 외 예외는 타입명+메시지로 표시한다.
    """
    try:
        from volo_engine.errors import VoloError
    except Exception:  # pragma: no cover
        VoloError = ()  # type: ignore[assignment]

    if isinstance(exc, VoloError):  # type: ignore[arg-type]
        return exc.user_message(), f"{type(exc).__name__}: {exc}"
    return (
        f"처리 중 오류가 발생했습니다: {exc}",
        f"{type(exc).__name__}: {exc}",
    )
