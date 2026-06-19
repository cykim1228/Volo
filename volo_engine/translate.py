"""번역(translate) 단계 — cue별 다국어 번역, 타임코드 보존.

세그멘테이션된 ``list[Subtitle]`` 을 받아 **cue 단위로 번역**하고, 결과를 각
:class:`~volo_engine.models.Subtitle` 의 ``translation[target_lang]`` 에 줄 리스트로
채운다. 타임코드(``start`` / ``end`` / ``index``)는 절대 변경하지 않으며(보존성 불변식),
번역된 텍스트만 대상 언어의 가독성 규칙으로 다시 줄 배분한다.

설계 원칙
---------
- **백엔드 교체형.** 실제 번역은 :class:`TranslateBackend` 프로토콜
  (``translate_lines(lines, src, tgt) -> lines``)을 구현한 객체가 수행한다. 이 모듈은
  오케스트레이션(cue 순회·줄 배분·결과 주입)만 담당하며 특정 번역 제공자에 의존하지 않는다.
- **모킹 금지.** 기본 백엔드를 가짜로 통과시키지 않는다. ``backend`` 미지정 시
  :class:`TranslateBackendNotConfiguredError` 를 명확히 던져 "번역 백엔드 미구성"을
  사용자에게 알린다(조용한 실패·플레이스홀더 출력 금지). 실제 백엔드(LLM/사전 API 등)는
  이 인터페이스를 구현해 주입한다.
- **stdlib만.** 결정적·경량 모듈로 유지하며 무거운 의존성을 import 하지 않는다.
  실제 번역 엔진 의존성은 주입되는 백엔드 구현 쪽에 둔다.

참조: ``.claude/skills/volo-engine-dev/references/subtitle-domain.md`` §6,
``docs/ARCHITECTURE.md`` §4.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .config import default_segment_rules
from .errors import VoloError
from .models import SegmentRules, Subtitle

__all__ = [
    "TranslateBackend",
    "TranslateError",
    "TranslateBackendNotConfiguredError",
    "translate",
    "wrap_lines",
]


# --------------------------------------------------------------------------- #
# 오류
# --------------------------------------------------------------------------- #


class TranslateError(VoloError):
    """번역(translate) 단계 실패의 베이스 오류."""


class TranslateBackendNotConfiguredError(TranslateError):
    """번역 백엔드가 주입되지 않아 번역을 수행할 수 없음.

    ``translate(..., backend=None)`` 처럼 백엔드 없이 호출되면 발생한다. MVP는
    인터페이스만 확정하고 기본 구현을 두지 않으므로(아키텍처 OQ3), 호출자는
    :class:`TranslateBackend` 구현을 명시적으로 주입해야 한다.
    """


# --------------------------------------------------------------------------- #
# 백엔드 인터페이스
# --------------------------------------------------------------------------- #


@runtime_checkable
class TranslateBackend(Protocol):
    """교체 가능한 번역 백엔드 인터페이스.

    실제 번역 제공자(LLM, 사전/번역 API, 사내 모델 등)는 이 프로토콜을 구현한 객체를
    :func:`translate` 에 주입한다. 이 모듈은 구현 세부를 모른 채 인터페이스로만 호출한다.

    구현 계약:
        - 입력 ``lines`` 의 **의미를 보존**하여 ``tgt`` 언어로 번역한다.
        - 반환은 번역된 텍스트 줄 리스트다. 줄 개수가 입력과 일치할 필요는 없다
          (호출 측에서 대상 언어 가독성 규칙으로 다시 줄 배분하므로). 단, cue 단위로
          호출되므로 한 cue의 의미가 줄 경계로 잘려도 합쳐서 번역되도록 구현해야 한다.
        - 타임스탬프·인덱스는 다루지 않는다(텍스트만).
    """

    def translate_lines(
        self, lines: list[str], src: str, tgt: str
    ) -> list[str]:
        """``lines`` 를 ``src`` → ``tgt`` 언어로 번역해 줄 리스트로 반환한다.

        Args:
            lines: 원본 언어 텍스트 줄들(한 cue의 1~2줄).
            src: 원본 언어 코드(ISO-639-1).
            tgt: 대상 언어 코드(ISO-639-1).

        Returns:
            번역된 텍스트 줄 리스트.
        """
        ...


# --------------------------------------------------------------------------- #
# 줄 배분 (대상 언어 가독성 규칙)
# --------------------------------------------------------------------------- #


def wrap_lines(text: str, rules: SegmentRules) -> list[str]:
    """번역된 텍스트를 대상 언어 가독성 규칙으로 1~``max_lines`` 줄에 배분한다.

    어절(공백) 경계에서 그리디하게 줄을 채우되, 각 줄이
    ``rules.max_chars_per_line`` 를 넘지 않게 한다. ``max_lines`` 줄을 채우고도
    텍스트가 남으면(자막 한 cue로는 과한 길이) 마지막 줄에 나머지를 모두 담아
    텍스트 유실을 막는다(타임코드는 공유하므로 cue를 늘리지 않는다). 한 어절이
    ``max_chars_per_line`` 보다 긴 경우는 분할 불가 예외로 그대로 한 줄에 둔다.

    Args:
        text: 줄바꿈을 재계산할 (번역된) 단일 문자열.
        rules: 대상 언어 줄 배분에 사용할 세그멘테이션 규칙.

    Returns:
        1~``max_lines`` 개의 줄 리스트. 입력이 공백뿐이면 ``[""]``.
    """
    words = text.split()
    if not words:
        return [""]

    max_chars = max(1, rules.max_chars_per_line)
    max_lines = max(1, rules.max_lines)

    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            candidate = word
        else:
            candidate = f"{current} {word}"
        # 현재 줄에 넣을 수 있으면 누적.
        if len(candidate) <= max_chars or not current:
            current = candidate
            continue
        # 줄이 가득 참 → 다음 줄로 넘긴다. 단, 이미 마지막 허용 줄이면
        # 더 쪼개지 않고 나머지를 이 줄에 계속 채운다(텍스트 유실 방지).
        if len(lines) >= max_lines - 1:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    # 안전장치: 빈 결과 방지.
    return lines or [""]


# --------------------------------------------------------------------------- #
# 공개 진입점
# --------------------------------------------------------------------------- #


def translate(
    subtitles: list[Subtitle],
    target_lang: str,
    *,
    backend: TranslateBackend | None = None,
    rules: SegmentRules | None = None,
) -> list[Subtitle]:
    """자막 cue들을 ``target_lang`` 으로 번역해 ``translation`` 에 채운다.

    각 :class:`~volo_engine.models.Subtitle` 의 원본 줄(``lines``)을 cue 단위로
    번역하고, 번역 결과를 대상 언어 가독성 규칙(``rules``)으로 다시 줄 배분한 뒤
    ``subtitle.translation[target_lang]`` 에 저장한다. **타임코드(``start`` /
    ``end`` / ``index``)와 원본 ``lines`` 는 변경하지 않는다**(보존성 불변식).

    입력 리스트의 ``Subtitle`` 객체를 제자리(in-place)에서 갱신하고 동일 리스트를
    반환한다. 이미 다른 언어 번역이 들어 있으면(``translation`` 이 ``None`` 이 아니면)
    해당 언어 키만 갱신하고 기존 키는 보존한다.

    Args:
        subtitles: 세그멘테이션된 원본 자막 cue 리스트.
        target_lang: 번역 대상 언어 코드(ISO-639-1, 예: ``"en"``, ``"ja"``).
        backend: 번역을 수행할 :class:`TranslateBackend` 구현. ``None`` 이면
            :class:`TranslateBackendNotConfiguredError` 를 던진다(모킹 금지).
        rules: 대상 언어 줄 배분 규칙. ``None`` 이면
            :func:`volo_engine.config.default_segment_rules` 의 기본값을 사용한다.

    Returns:
        번역 줄이 채워진 동일한 ``list[Subtitle]``.

    Raises:
        TranslateBackendNotConfiguredError: ``backend`` 가 주입되지 않은 경우.
        TranslateError: 번역 대상 언어 코드가 비었거나, 백엔드 호출이 실패한 경우.
    """
    if not target_lang:
        raise TranslateError(
            "번역 대상 언어가 지정되지 않았습니다.",
            hint="ISO-639-1 언어 코드를 지정하세요(예: 'en', 'ja').",
        )

    if backend is None:
        raise TranslateBackendNotConfiguredError(
            "번역 백엔드 미구성: 번역을 수행할 백엔드가 주입되지 않았습니다.",
            hint=(
                "TranslateBackend(translate_lines(lines, src, tgt) -> lines) 를 "
                "구현한 객체를 translate(..., backend=...) 로 주입하세요."
            ),
        )

    effective_rules = rules if rules is not None else default_segment_rules()

    for sub in subtitles:
        src_lang = sub.lang
        # 원본과 대상 언어가 같으면 원본 줄을 그대로 번역 슬롯에 복제(불필요 호출 회피).
        if src_lang == target_lang:
            translated_lines = list(sub.lines)
        else:
            try:
                raw = backend.translate_lines(
                    list(sub.lines), src_lang, target_lang
                )
            except VoloError:
                # 백엔드가 이미 Volo 오류를 던지면 그대로 전파.
                raise
            except Exception as exc:  # noqa: BLE001 — 백엔드 오류를 사용자 메시지로 래핑
                raise TranslateError(
                    f"번역 백엔드 호출 실패(cue {sub.index}, "
                    f"{src_lang}→{target_lang}): {exc}",
                    hint="백엔드 구현/네트워크/인증 설정을 확인하세요.",
                ) from exc

            joined = " ".join(line.strip() for line in raw if line.strip())
            translated_lines = wrap_lines(joined, effective_rules)

        # 타임코드·원본 줄 보존: translation 매핑만 갱신.
        if sub.translation is None:
            sub.translation = {}
        sub.translation[target_lang] = translated_lines

    return subtitles
