"""오디오 추출 — 영상/오디오 파일에서 16kHz mono PCM WAV 추출.

faster-whisper 계열은 16kHz mono PCM 입력을 선호한다(subtitle-domain §1). 이 모듈은
ffmpeg 로 입력 미디어에서 오디오 트랙만 뽑아 정규화하고, ``tempfile`` 기반 임시 WAV
경로를 반환한다.

ffmpeg 바이너리 탐색 순서:
    1. 시스템 PATH 의 ``ffmpeg``.
    2. ``imageio_ffmpeg.get_ffmpeg_exe()`` 번들 바이너리(폴백).
    3. 둘 다 없으면 :class:`~volo_engine.errors.VoloDependencyError` + 설치 안내.

얕은 ``__init__`` 정책(ARCHITECTURE §3): 무거운/외부 의존(``shutil``/``subprocess`` 는
가볍지만 ``imageio_ffmpeg``)은 함수 내부에서만 import 한다. 모킹 금지 — 실제 ffmpeg 를 호출한다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .config import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE, SUPPORTED_INPUT_SUFFIXES
from .errors import VoloAudioError, VoloDependencyError, VoloInputError

__all__ = ["resolve_ffmpeg", "extract_audio", "build_audio_filters"]


def build_audio_filters(*, denoise: bool, normalize: bool) -> str:
    """STT 정확도를 높이는 ffmpeg 오디오 필터 체인(``-af`` 인자)을 만든다.

    실제 영상은 잡음·들쭉날쭉한 음량 때문에 인식률이 떨어진다. 다음 필터로 보정한다
    (subtitle-domain §1):

    - ``highpass=f=80`` — 80Hz 이하 저주파 럼블/바람소리 제거(denoise).
    - ``afftdn=nf=-25`` — FFT 기반 광대역 잡음 감쇠(가벼운 강도, denoise).
    - ``loudnorm=I=-16:TP=-1.5:LRA=11`` — EBU R128 음량 정규화(작은 음성을 키움, normalize).

    Args:
        denoise: 잡음 제거(highpass+afftdn) 적용 여부.
        normalize: 음량 정규화(loudnorm) 적용 여부.

    Returns:
        쉼표로 연결된 필터 문자열. 둘 다 ``False`` 면 빈 문자열(필터 미적용).
    """
    filters: list[str] = []
    if denoise:
        filters.append("highpass=f=80")
        filters.append("afftdn=nf=-25")
    if normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    return ",".join(filters)


# ffmpeg 미설치 시 사용자에게 보여줄 설치 안내(VoloDependencyError.hint).
_FFMPEG_INSTALL_HINT = (
    "ffmpeg 가 필요합니다. 다음 중 하나로 해결하세요: "
    "(1) ffmpeg 를 설치하고 PATH 에 추가 (Windows: `winget install Gyan.FFmpeg`, "
    "macOS: `brew install ffmpeg`, Linux: `apt install ffmpeg`), 또는 "
    "(2) `pip install imageio-ffmpeg` 로 번들 바이너리를 설치하세요."
)


def resolve_ffmpeg() -> str:
    """사용할 ffmpeg 실행 파일 경로를 결정한다.

    탐색 순서는 시스템 PATH → ``imageio_ffmpeg`` 번들 바이너리다. 둘 다 없으면
    설치 안내와 함께 :class:`VoloDependencyError` 를 던진다.

    Returns:
        ffmpeg 실행 파일의 절대(또는 PATH 해석 가능) 경로 문자열.

    Raises:
        VoloDependencyError: 시스템 PATH 와 ``imageio_ffmpeg`` 양쪽에서 ffmpeg 를
            찾지 못한 경우. ``hint`` 에 설치 방법을 담는다.
    """
    # 1) 시스템 PATH 우선.
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    # 2) imageio-ffmpeg 번들 바이너리 폴백(함수 내부 import — 얕은 __init__ 정책).
    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]
    except ImportError:
        raise VoloDependencyError(
            "ffmpeg 를 찾을 수 없습니다(시스템 PATH·imageio-ffmpeg 모두 없음).",
            hint=_FFMPEG_INSTALL_HINT,
        ) from None

    try:
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # imageio-ffmpeg 내부 다운로드/탐색 실패
        raise VoloDependencyError(
            "imageio-ffmpeg 번들 ffmpeg 바이너리를 가져오지 못했습니다.",
            hint=_FFMPEG_INSTALL_HINT,
        ) from exc

    if not bundled or not os.path.exists(bundled):
        raise VoloDependencyError(
            "imageio-ffmpeg 가 유효한 ffmpeg 바이너리를 제공하지 않았습니다.",
            hint=_FFMPEG_INSTALL_HINT,
        )
    return bundled


def extract_audio(
    video_path: str,
    *,
    sample_rate: int = AUDIO_SAMPLE_RATE,
    channels: int = AUDIO_CHANNELS,
    tmp_dir: str | None = None,
    denoise: bool = True,
    normalize: bool = True,
) -> str:
    """영상/오디오 파일에서 16kHz mono PCM WAV 를 추출해 임시 파일 경로를 반환한다.

    ffmpeg 명령(subtitle-domain §1)::

        ffmpeg -hide_banner -loglevel error -i <video> -vn \\
            [-af <filters>] -ac <channels> -ar <sample_rate> -c:a pcm_s16le -y <out.wav>

    ``denoise`` / ``normalize`` 가 켜져 있으면 :func:`build_audio_filters` 의 필터 체인을
    ``-af`` 로 적용해 잡음을 줄이고 음량을 정규화한다(STT 정확도 향상). 임시 WAV 는
    ``tempfile`` 로 생성되며, 호출자(또는 pipeline)가 사용 후 정리할 책임이 있다.
    추출 실패 시 임시 파일은 이 함수가 정리한다.

    Args:
        video_path: 입력 영상/오디오 파일 경로.
        sample_rate: 출력 WAV 샘플레이트(Hz). 기본 ``AUDIO_SAMPLE_RATE`` (16000).
        channels: 출력 채널 수. 기본 ``AUDIO_CHANNELS`` (1, mono).
        tmp_dir: 임시 WAV 를 생성할 디렉토리. ``None`` 이면 시스템 기본 임시 디렉토리.
        denoise: 잡음 제거 필터 적용 여부(기본 ``True``).
        normalize: 음량 정규화 필터 적용 여부(기본 ``True``).

    Returns:
        생성된 16kHz mono PCM WAV 파일의 절대 경로 문자열.

    Raises:
        VoloInputError: ``video_path`` 가 존재하지 않거나 파일이 아닌 경우, 또는
            ``sample_rate`` / ``channels`` 가 1 미만인 경우.
        VoloDependencyError: ffmpeg 바이너리를 찾지 못한 경우(설치 안내 포함).
        VoloAudioError: ffmpeg 가 0이 아닌 종료 코드로 실패하거나 출력 WAV 가
            생성되지 않은 경우(ffmpeg stderr 포함).
    """
    if not isinstance(video_path, str) or not video_path:
        raise VoloInputError("입력 경로(video_path)가 비어 있습니다.")
    if not os.path.exists(video_path):
        raise VoloInputError(
            f"입력 파일을 찾을 수 없습니다: {video_path}",
            hint="경로가 올바른지, 파일이 존재하는지 확인하세요.",
        )
    if not os.path.isfile(video_path):
        raise VoloInputError(f"입력 경로가 파일이 아닙니다: {video_path}")
    if sample_rate < 1:
        raise VoloInputError(f"sample_rate 는 1 이상이어야 합니다: {sample_rate}")
    if channels < 1:
        raise VoloInputError(f"channels 는 1 이상이어야 합니다: {channels}")

    suffix = os.path.splitext(video_path)[1].lower()
    if suffix and suffix not in SUPPORTED_INPUT_SUFFIXES:
        # 경고성 안내만: ffmpeg 가 처리 가능한 컨테이너도 있으므로 차단하지 않고 진행.
        # (config.SUPPORTED_INPUT_SUFFIXES 는 검증용 화이트리스트일 뿐.)
        pass

    ffmpeg_exe = resolve_ffmpeg()

    if tmp_dir is not None and not os.path.isdir(tmp_dir):
        raise VoloInputError(f"tmp_dir 가 존재하는 디렉토리가 아닙니다: {tmp_dir}")

    # 임시 WAV 경로 생성(파일 핸들은 즉시 닫고 경로만 사용 — ffmpeg 가 직접 기록).
    fd, out_path = tempfile.mkstemp(suffix=".wav", prefix="volo_audio_", dir=tmp_dir)
    os.close(fd)

    cmd = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-vn",  # 비디오 스트림 제거
    ]
    # STT 정확도 향상 필터(잡음 제거·음량 정규화). 둘 다 꺼져 있으면 미적용.
    audio_filters = build_audio_filters(denoise=denoise, normalize=normalize)
    if audio_filters:
        cmd += ["-af", audio_filters]
    cmd += [
        "-ac",
        str(channels),  # 채널 수(mono=1)
        "-ar",
        str(sample_rate),  # 샘플레이트(16000)
        "-c:a",
        "pcm_s16le",  # 16-bit PCM
        "-y",  # 출력 덮어쓰기
        out_path,
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        _cleanup(out_path)
        raise VoloAudioError(
            f"ffmpeg 실행에 실패했습니다: {exc}",
            hint=_FFMPEG_INSTALL_HINT,
        ) from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        _cleanup(out_path)
        raise VoloAudioError(
            f"오디오 추출(ffmpeg)이 실패했습니다 (exit {proc.returncode}).",
            hint=stderr or "입력 파일에 오디오 트랙이 있는지, 포맷이 유효한지 확인하세요.",
        )

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        _cleanup(out_path)
        raise VoloAudioError(
            "ffmpeg 가 오디오를 추출하지 못했습니다(출력 WAV 가 비어 있음).",
            hint="입력 파일에 오디오 트랙이 포함되어 있는지 확인하세요.",
        )

    return out_path


def _cleanup(path: str) -> None:
    """추출 실패 시 남은 임시 파일을 조용히 제거한다(정리 실패는 무시)."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
