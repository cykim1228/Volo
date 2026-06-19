"""스타일 프리셋(style) 단계 — 프리셋 로드/적용/사이드카 출력.

자막 스타일 프리셋(폰트/색/위치)을 정의·로드하고, 세그멘테이션된 ``Subtitle`` cue에
프리셋을 메타로 적용한다(``Subtitle.style`` 에 프리셋 이름 설정). SRT/VTT 는 스타일을
담지 못하므로 프리셋 정보는 export 시 사이드카(``name.style.json``)로 함께 출력되어
프리미어 캡션 트랙 적용 가이드의 근거가 된다(subtitle-domain §8).

이 모듈은 **결정적·stdlib만** 사용한다(무거운 의존성 import 금지). 동일 입력에
대해 동일 출력을 내며 외부 의존 없이 pytest 로 검증 가능하다.

데이터 모델(:mod:`volo_engine.models`)의 :class:`StylePreset` / :class:`Subtitle`
타입만 사용한다.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import replace
from pathlib import Path

from .config import PRESETS_DIR
from .errors import VoloExportError, VoloInputError
from .models import StylePreset, Subtitle

__all__ = [
    "STYLE_SIDECAR_SUFFIX",
    "load_preset",
    "list_presets",
    "apply_style",
    "write_style_sidecar",
]

# export 시 함께 출력되는 스타일 사이드카 파일 접미사(``<name>.style.json``).
STYLE_SIDECAR_SUFFIX = ".style.json"

# StylePreset 의 필드 이름 집합(JSON 검증용). dataclass 정의에서 파생해
# models.py 가 바뀌면 자동으로 따라간다.
_PRESET_FIELDS: tuple[str, ...] = tuple(
    f.name for f in dataclasses.fields(StylePreset)
)


def _preset_path(name: str) -> Path:
    """프리셋 이름 → ``assets/presets/<name>.json`` 경로를 계산한다.

    Args:
        name: 프리셋 식별 이름(예: ``"default"``). 경로 구분자/상위 경로(``..``)는
            허용하지 않는다(디렉토리 탈출 방지).

    Returns:
        프리셋 JSON 파일의 절대 경로.

    Raises:
        VoloInputError: 이름이 비었거나 경로 구분자/``..`` 를 포함할 때.
    """
    if not name or not name.strip():
        raise VoloInputError(
            "스타일 프리셋 이름이 비어 있습니다.",
            hint="default / youtube / interview 중 하나를 지정하세요.",
        )
    # 경로 탈출 방지: 단일 파일명만 허용.
    if name != Path(name).name or name in (".", ".."):
        raise VoloInputError(
            f"잘못된 프리셋 이름입니다: {name!r}",
            hint="경로 구분자 없이 프리셋 이름만 지정하세요(예: 'default').",
        )
    return PRESETS_DIR / f"{name}.json"


def load_preset(name: str) -> StylePreset:
    """이름으로 스타일 프리셋을 로드한다.

    ``assets/presets/<name>.json`` 을 읽어 :class:`StylePreset` 로 역직렬화한다.
    JSON 의 키는 :class:`StylePreset` 필드와 1:1 대응해야 한다.

    Args:
        name: 프리셋 이름(예: ``"default"``, ``"youtube"``, ``"interview"``).

    Returns:
        역직렬화된 :class:`StylePreset`.

    Raises:
        VoloInputError: 이름이 잘못되었거나, 프리셋 파일이 없거나, JSON 형식/필드가
            올바르지 않을 때.
    """
    path = _preset_path(name)
    if not path.is_file():
        available = ", ".join(list_presets()) or "(없음)"
        raise VoloInputError(
            f"스타일 프리셋을 찾을 수 없습니다: {name!r}",
            hint=f"사용 가능한 프리셋: {available}",
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:  # 권한/IO 오류
        raise VoloInputError(
            f"스타일 프리셋 파일을 읽을 수 없습니다: {path}",
            hint=str(exc),
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VoloInputError(
            f"스타일 프리셋 JSON 형식이 올바르지 않습니다: {path}",
            hint=str(exc),
        ) from exc

    return _preset_from_dict(data, source=path, default_name=name)


def _preset_from_dict(
    data: object, *, source: Path, default_name: str
) -> StylePreset:
    """dict → :class:`StylePreset` 로 변환·검증한다.

    Args:
        data: ``json.loads`` 결과(객체여야 함).
        source: 진단 메시지용 원본 경로.
        default_name: JSON 에 ``name`` 이 없을 때 사용할 기본 이름(파일명).

    Returns:
        검증된 :class:`StylePreset`.

    Raises:
        VoloInputError: 객체가 아니거나, 알 수 없는 키가 있거나, 필수 필드가 빠졌을 때.
    """
    if not isinstance(data, dict):
        raise VoloInputError(
            f"스타일 프리셋은 JSON 객체여야 합니다: {source}",
            hint=f"최상위 타입이 {type(data).__name__} 입니다.",
        )

    unknown = set(data) - set(_PRESET_FIELDS)
    if unknown:
        raise VoloInputError(
            f"스타일 프리셋에 알 수 없는 키가 있습니다: {sorted(unknown)} ({source})",
            hint=f"허용 키: {list(_PRESET_FIELDS)}",
        )

    # name 이 없으면 파일명으로 보충(파일명과 내부 name 일관성 유지).
    values = dict(data)
    values.setdefault("name", default_name)

    missing = [f for f in _PRESET_FIELDS if f not in values]
    if missing:
        raise VoloInputError(
            f"스타일 프리셋에 필수 필드가 없습니다: {missing} ({source})",
            hint=f"필요 필드: {list(_PRESET_FIELDS)}",
        )

    return StylePreset(**values)


def list_presets() -> list[str]:
    """``assets/presets/`` 에 존재하는 프리셋 이름 목록을 반환한다.

    ``<name>.json`` 파일들의 stem 을 정렬해 돌려준다(사이드카 ``*.style.json`` 제외).
    프리셋 디렉토리가 없으면 빈 리스트.

    Returns:
        정렬된 프리셋 이름 리스트.
    """
    if not PRESETS_DIR.is_dir():
        return []
    names = [
        p.stem
        for p in PRESETS_DIR.glob("*.json")
        if not p.name.endswith(STYLE_SIDECAR_SUFFIX)
    ]
    return sorted(names)


def apply_style(subtitles: list[Subtitle], preset: StylePreset) -> list[Subtitle]:
    """자막 cue 목록에 스타일 프리셋을 적용한다(메타 보존).

    각 :class:`Subtitle` 의 ``style`` 필드를 ``preset.name`` 으로 설정한 **새 리스트**를
    반환한다. SRT/VTT 는 스타일을 담지 못하므로 실제 폰트/색/위치는 export 사이드카와
    프리미어 캡션 트랙에서 사용된다. 타임스탬프·텍스트·번역 등 다른 필드는 변경하지
    않는다(보존성). 입력 리스트와 각 cue 는 변형하지 않는다(결정적·부작용 없음).

    Args:
        subtitles: 세그멘테이션(필요 시 번역)된 자막 cue 목록.
        preset: 적용할 스타일 프리셋. ``preset.name`` 이 각 cue 의 ``style`` 에 설정된다.

    Returns:
        ``style`` 이 ``preset.name`` 으로 채워진 새 :class:`Subtitle` 리스트.
    """
    return [replace(sub, style=preset.name) for sub in subtitles]


def write_style_sidecar(preset: StylePreset, out_path: str) -> str:
    """스타일 프리셋을 사이드카 JSON(``<base>.style.json``)으로 출력한다.

    자막 파일(``name.srt`` / ``name.vtt``) 옆에 스타일 메타를 동봉해, 사용자가 프리미어
    캡션 트랙에 폰트/색/위치를 동일하게 적용할 수 있게 한다(subtitle-domain §8).

    경로 규칙:
        - ``out_path`` 가 자막 파일 경로(``foo.srt``)면 확장자를 떼고
          ``foo.style.json`` 으로 출력한다.
        - 이미 ``.style.json`` 으로 끝나면 그대로 사용한다.
        - 그 외(확장자 없음)면 ``out_path + ".style.json"``.

    Args:
        preset: 출력할 :class:`StylePreset`.
        out_path: 기준 출력 경로(보통 export 한 자막 파일 경로).

    Returns:
        실제로 기록한 사이드카 파일의 경로(문자열).

    Raises:
        VoloExportError: 디렉토리 생성/파일 쓰기에 실패할 때.
    """
    sidecar = _sidecar_path(out_path)
    payload = json.dumps(
        dataclasses.asdict(preset), ensure_ascii=False, indent=2
    )
    try:
        parent = sidecar.parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        # 사이드카는 UTF-8(BOM 없이), 줄바꿈 LF 고정.
        sidecar.write_text(payload + "\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        raise VoloExportError(
            f"스타일 사이드카를 쓸 수 없습니다: {sidecar}",
            hint=str(exc),
        ) from exc
    return str(sidecar)


def _sidecar_path(out_path: str) -> Path:
    """기준 출력 경로 → 스타일 사이드카(``<base>.style.json``) 경로를 계산한다.

    Args:
        out_path: 기준 경로(자막 파일 경로 또는 베이스 경로).

    Returns:
        사이드카 파일 경로.

    Raises:
        VoloExportError: ``out_path`` 가 비었을 때.
    """
    if not out_path or not str(out_path).strip():
        raise VoloExportError(
            "스타일 사이드카 출력 경로가 비어 있습니다.",
            hint="export 한 자막 파일 경로를 전달하세요.",
        )
    path = Path(out_path)
    if path.name.endswith(STYLE_SIDECAR_SUFFIX):
        return path
    # ``foo.srt`` → ``foo.style.json`` (확장자만 교체).
    return path.with_name(f"{path.stem}{STYLE_SIDECAR_SUFFIX}")
