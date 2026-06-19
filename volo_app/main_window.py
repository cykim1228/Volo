"""volo_app.main_window — Volo 데스크톱 메인 윈도우(PySide6).

편집자가 코드 없이 쓰는 단일 창 UI. 사용자 플로우(PRD §2 / docs/ARCHITECTURE §6):

    영상 드래그앤드롭/선택 → 옵션 설정 → "자막 생성"(진행률) →
    cue 미리보기/인라인 편집 → 출력폴더 선택 → 내보내기 → 프리미어 임포트 안내

엔진 분리
---------
- 생성은 :class:`volo_app.worker.PipelineWorker` 가 :func:`volo_engine.pipeline.run` 을 호출(워커 스레드).
- 미리보기는 엔진이 생성한 SRT/VTT 파일을 읽어 cue 행으로 채운다. 인라인 텍스트 편집 후
  내보내기는 :func:`volo_engine.export.export` 를 **직접 호출**(공개 엔진 함수)해 다시 쓴다.
  → STT/세그멘테이션을 UI에서 재구현하지 않는다.

디자인
------
다크 테마 + 카드 레이아웃 + 강조색(인디고). 스타일은 모듈 상수 :data:`STYLE`(QSS)로 정의하고
``volo_app.__main__`` 이 ``QApplication`` 에 적용해 다이얼로그까지 일관 테마를 입힌다.

PySide6 미설치 환경
-------------------
PySide6 가 없으면 import 시 :data:`PYSIDE_AVAILABLE` 가 ``False`` 가 되고, 위젯 클래스는
정의되지 않는다(파일 자체는 정상 import). 실제 실행은 ``__main__`` 에서 안내 후 종료.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

try:
    from PySide6.QtCore import Qt, QThread
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    PYSIDE_AVAILABLE = True
except Exception:  # pragma: no cover - PySide6 미설치 환경
    PYSIDE_AVAILABLE = False


# --------------------------------------------------------------------------- #
# 테마 (QSS) — __main__ 이 QApplication 에 적용
# --------------------------------------------------------------------------- #

# 색: 배경 #16181D · 카드 #1F222A · 보더 #2C3039 · 본문 #E6E8EC · 뮤트 #9AA0AB · 강조 #6C7BFF
STYLE = """
QWidget { background: #16181D; color: #E6E8EC; font-family: 'Malgun Gothic','Segoe UI',sans-serif; font-size: 13px; }
QMainWindow { background: #16181D; }
QToolTip { background: #2A2E37; color: #E6E8EC; border: 1px solid #3A4150; padding: 4px 6px; }

#appTitle { font-size: 24px; font-weight: 800; color: #FFFFFF; }
#appSubtitle { font-size: 12px; color: #9AA0AB; }
#accentBar { background: #6C7BFF; border-radius: 2px; }
#footer { background: #16181D; border-top: 1px solid #23262F; }
QScrollArea { background: #16181D; border: none; }

QFrame#card { background: #1F222A; border: 1px solid #2C3039; border-radius: 14px; }
#cardTitle { font-size: 11px; font-weight: 800; color: #8E96A3; }
QLabel#muted { color: #9AA0AB; }
QLabel#fileChip { background: #20242D; border: 1px solid #2C3039; border-radius: 8px; padding: 7px 12px; color: #C9CED8; }

#dropArea {
  border: 2px dashed #3A4150; border-radius: 12px; background: #1A1D24;
  color: #8A919E; font-size: 14px; padding: 26px;
}
#dropArea:hover { border-color: #6C7BFF; color: #C9CED8; background: #1C2030; }

QLabel { background: transparent; }
QFormLayout > QLabel, QFormLayout QLabel { color: #B7BDC9; }

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
  background: #15171C; border: 1px solid #333845; border-radius: 8px;
  padding: 7px 10px; color: #E6E8EC; selection-background-color: #6C7BFF; min-height: 16px;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #444C5E; }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #6C7BFF; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { width: 0; height: 0; }
QComboBox QAbstractItemView {
  background: #1F222A; border: 1px solid #2C3039; border-radius: 8px;
  selection-background-color: #6C7BFF; color: #E6E8EC; outline: none; padding: 4px;
}

QCheckBox { spacing: 8px; color: #C9CED8; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid #444C5E; background: #15171C; }
QCheckBox::indicator:checked { background: #6C7BFF; border-color: #6C7BFF; }

QPushButton {
  background: #262A33; border: 1px solid #353B47; border-radius: 9px;
  padding: 9px 16px; color: #E6E8EC; font-weight: 600;
}
QPushButton:hover { background: #2E333E; border-color: #444C5E; }
QPushButton:disabled { color: #5A606C; background: #1C1F26; border-color: #2A2E37; }

QPushButton#primary {
  background: #6C7BFF; border: none; color: #FFFFFF; font-size: 14px; font-weight: 700; padding: 12px 18px;
}
QPushButton#primary:hover { background: #8090FF; }
QPushButton#primary:disabled { background: #2E3142; color: #6E7486; }

QProgressBar {
  background: #15171C; border: 1px solid #2C3039; border-radius: 8px;
  height: 16px; text-align: center; color: #C9CED8; font-size: 11px;
}
QProgressBar::chunk { background: #6C7BFF; border-radius: 7px; }

QTableWidget {
  background: #15171C; border: 1px solid #2C3039; border-radius: 10px;
  gridline-color: #23262F; color: #E6E8EC; outline: none;
}
QHeaderView::section {
  background: #20242D; color: #9AA0AB; border: none; border-bottom: 1px solid #2C3039; padding: 8px; font-weight: 700;
}
QTableWidget::item { padding: 5px 8px; }
QTableWidget::item:selected { background: #2C3350; color: #FFFFFF; }
QTableCornerButton::section { background: #20242D; border: none; }

QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: #3A4150; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4A5263; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: #3A4150; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


# 입력으로 허용할 미디어 확장자(검증용. 최종 검증은 엔진이 수행).
_MEDIA_EXTS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv",  # 영상
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg",          # 오디오
}

# UI에 노출할 모델 크기 후보(엔진은 임의 문자열 허용. 흔한 선택지만 제공).
_MODEL_SIZES = ["large-v3", "large-v3-turbo", "large-v2", "medium", "small", "base"]
_DEVICES = ["auto", "cuda", "cpu"]
# 번역 대상 언어 후보("(없음)" = 번역 생략). 번역엔 실제 백엔드가 필요(모킹 금지).
_TRANSLATE_LANGS = ["(없음)", "en", "ja", "zh", "es", "fr", "de"]


# --------------------------------------------------------------------------- #
# SRT/VTT 파싱 (미리보기 — 엔진 산출 파일을 cue 행으로 환원)
# --------------------------------------------------------------------------- #


@dataclass
class CueRow:
    """미리보기 테이블 한 행(= 한 cue). 내부 표현은 초 단위 float."""

    index: int
    start: float
    end: float
    text: str  # 화면 줄들을 \n 로 합친 편집용 텍스트


_TC_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _tc_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_subtitle_file(path: str) -> list[CueRow]:
    """SRT/VTT 파일을 cue 행 리스트로 파싱한다(미리보기용, 관대한 파서).

    엔진의 export 결과를 다시 읽는 용도라 표준 구조를 가정하되, BOM/CRLF/WEBVTT 헤더를
    너그럽게 처리한다. 파싱 실패 시 빈 리스트를 반환한다(미리보기는 보조 기능).
    """
    try:
        with open(path, encoding="utf-8-sig") as fh:
            content = fh.read()
    except OSError:
        return []

    content = content.replace("\r\n", "\n").replace("\r", "\n")
    # 빈 줄(하나 이상)로 블록 분리. WEBVTT 헤더 블록은 타임코드가 없어 자연히 제외된다.
    blocks = re.split(r"\n\s*\n", content)
    rows: list[CueRow] = []
    idx = 1
    for block in blocks:
        lines = block.split("\n")
        tc_match = None
        tc_line_pos = -1
        for i, ln in enumerate(lines):
            m = _TC_RE.search(ln)
            if m:
                tc_match = m
                tc_line_pos = i
                break
        if tc_match is None:
            continue
        start = _tc_to_seconds(tc_match.group(1), tc_match.group(2), tc_match.group(3), tc_match.group(4))
        end = _tc_to_seconds(tc_match.group(5), tc_match.group(6), tc_match.group(7), tc_match.group(8))
        text_lines = [ln for ln in lines[tc_line_pos + 1 :] if ln.strip() != ""]
        rows.append(CueRow(index=idx, start=start, end=end, text="\n".join(text_lines)))
        idx += 1
    return rows


def seconds_to_srt_tc(value: float) -> str:
    """초(float) → ``HH:MM:SS,mmm`` (미리보기 표시용)."""
    if value < 0:
        value = 0.0
    total_ms = int(round(value * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# --------------------------------------------------------------------------- #
# 메인 윈도우
# --------------------------------------------------------------------------- #

if PYSIDE_AVAILABLE:

    class DropArea(QLabel):
        """드래그앤드롭 + 클릭 선택을 받는 영역. 선택된 파일 경로를 부모에 전달한다."""

        def __init__(self, on_files: Any) -> None:
            super().__init__()
            self._on_files = on_files
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setAcceptDrops(True)
            self.setMinimumHeight(120)
            self.setWordWrap(True)
            self.setObjectName("dropArea")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setText(
                "🎬   여기에 영상·오디오 파일을 끌어다 놓으세요\n\n"
                "또는 클릭해서 선택  ·  mp4 · mov · mkv · wav · mp3 …"
            )

        # 클릭 선택 -------------------------------------------------------- #
        def mousePressEvent(self, event: Any) -> None:
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "영상/오디오 파일 선택",
                "",
                "미디어 파일 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wav *.mp3 *.m4a *.flac);;모든 파일 (*.*)",
            )
            if paths:
                self._on_files(list(paths))

        # 드래그앤드롭 ----------------------------------------------------- #
        def dragEnterEvent(self, event: Any) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                event.ignore()

        def dropEvent(self, event: Any) -> None:
            paths: list[str] = []
            for url in event.mimeData().urls():
                local = url.toLocalFile()
                if local:
                    paths.append(local)
            if paths:
                self._on_files(paths)
                event.acceptProposedAction()

    class MainWindow(QMainWindow):
        """Volo 메인 윈도우. 투입 → 옵션 → 생성 → 미리보기/편집 → 내보내기."""

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Volo — AI 자동 자막 생성")
            self.resize(1060, 880)
            self.setMinimumSize(900, 720)

            self._video_path: str | None = None
            self._out_dir: str | None = None
            self._glossary_path: str | None = None
            self._thread: QThread | None = None
            self._worker: Any | None = None
            self._last_result: dict[str, Any] | None = None
            self._preview_path: str | None = None

            central = QWidget()
            self.setCentralWidget(central)
            outer = QVBoxLayout(central)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            # 내용이 창 높이를 넘으면 압축되지 않고 스크롤되도록 스크롤 영역으로 감싼다.
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            content = QWidget()
            body = QVBoxLayout(content)
            body.setContentsMargins(26, 22, 26, 14)
            body.setSpacing(16)
            body.addLayout(self._build_header())
            body.addWidget(self._build_input_card())
            body.addWidget(self._build_options_card())
            body.addWidget(self._build_run_card())
            body.addWidget(self._build_preview_card())
            body.addStretch(0)
            scroll.setWidget(content)
            outer.addWidget(scroll, 1)

            # 내보내기 바는 하단에 고정.
            footer = QWidget()
            footer.setObjectName("footer")
            frow = footer_layout = self._build_export_row()
            footer_wrap = QHBoxLayout(footer)
            footer_wrap.setContentsMargins(26, 12, 26, 16)
            footer_wrap.addLayout(frow)
            outer.addWidget(footer)

            self._set_busy(False)

        # ---------------- 카드 헬퍼 ---------------- #
        def _make_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
            card = QFrame()
            card.setObjectName("card")
            v = QVBoxLayout(card)
            v.setContentsMargins(20, 16, 20, 18)
            v.setSpacing(12)
            label = QLabel(title)
            label.setObjectName("cardTitle")
            v.addWidget(label)
            return card, v

        # ---------------- 헤더 ---------------- #
        def _build_header(self) -> QVBoxLayout:
            box = QVBoxLayout()
            box.setSpacing(4)
            title = QLabel("🎬  Volo")
            title.setObjectName("appTitle")
            subtitle = QLabel("AI 자동 자막 생성  ·  로컬 Whisper  ·  한국어 최적화 → 프리미어 임포트")
            subtitle.setObjectName("appSubtitle")
            bar = QFrame()
            bar.setObjectName("accentBar")
            bar.setFixedSize(60, 4)
            box.addWidget(title)
            box.addWidget(subtitle)
            box.addSpacing(4)
            box.addWidget(bar)
            return box

        # ---------------- 입력 카드 ---------------- #
        def _build_input_card(self) -> QFrame:
            card, v = self._make_card("입력")
            self._drop = DropArea(self._on_files_selected)
            v.addWidget(self._drop)
            self._file_label = QLabel("선택된 파일이 없습니다")
            self._file_label.setObjectName("fileChip")
            v.addWidget(self._file_label)
            return card

        # ---------------- 옵션 카드 ---------------- #
        def _build_options_card(self) -> QFrame:
            card, v = self._make_card("옵션")

            form = QFormLayout()
            form.setSpacing(10)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self._model_combo = QComboBox()
            self._model_combo.addItems(_MODEL_SIZES)
            self._model_combo.setToolTip("large-v3: 한국어 정확도 최상(느림) · turbo/medium: 빠름")
            form.addRow("모델 크기", self._model_combo)

            self._lang_edit = QLineEdit("ko")
            self._lang_edit.setPlaceholderText("ko / en … (비우면 자동감지)")
            form.addRow("언어", self._lang_edit)

            self._device_combo = QComboBox()
            self._device_combo.addItem("자동 (GPU 우선 → 실패 시 CPU)", "auto")
            self._device_combo.addItem("GPU (CUDA)", "cuda")
            self._device_combo.addItem("CPU (느리지만 항상 동작)", "cpu")
            self._device_combo.setToolTip(
                "자동: GPU가 float16/CUDA를 지원 못 하면 자동으로 CPU로 폴백합니다. "
                "GPU에서 계속 실패하면 CPU를 직접 선택하세요."
            )
            form.addRow("디바이스", self._device_combo)

            # 인식 힌트(프롬프트) — STT 품질 핵심 지렛대.
            self._prompt_edit = QLineEdit()
            self._prompt_edit.setPlaceholderText("예: 의료 인터뷰, 당뇨병·인슐린 용어 등장 (고유명사 인식↑)")
            self._prompt_edit.setToolTip("인식 단계 힌트(initial_prompt). 고유명사·도메인 어휘를 넣으면 정확도가 올라갑니다.")
            form.addRow("인식 힌트", self._prompt_edit)

            # 글로서리(JSON) 파일 선택.
            gloss_row = QHBoxLayout()
            gloss_row.setSpacing(8)
            self._glossary_label = QLabel("(선택 안 함)")
            self._glossary_label.setObjectName("muted")
            gloss_btn = QPushButton("JSON 선택…")
            gloss_btn.clicked.connect(self._on_pick_glossary)
            gloss_clear = QPushButton("지우기")
            gloss_clear.clicked.connect(self._on_clear_glossary)
            self._gloss_btn = gloss_btn
            self._gloss_clear = gloss_clear
            gloss_row.addWidget(self._glossary_label, 1)
            gloss_row.addWidget(gloss_btn)
            gloss_row.addWidget(gloss_clear)
            gloss_wrap = QWidget()
            gloss_wrap.setLayout(gloss_row)
            form.addRow("글로서리", gloss_wrap)

            # 줄바꿈/타이밍 — 가독성 규칙.
            read_row = QHBoxLayout()
            read_row.setSpacing(8)
            self._maxchars_spin = QSpinBox()
            self._maxchars_spin.setRange(8, 40)
            self._maxchars_spin.setValue(20)
            self._maxchars_spin.setToolTip("자막 한 줄 최대 글자수(한국어 권장 16~20)")
            self._maxcps_spin = QDoubleSpinBox()
            self._maxcps_spin.setRange(5.0, 40.0)
            self._maxcps_spin.setSingleStep(0.5)
            self._maxcps_spin.setValue(17.0)
            self._maxcps_spin.setToolTip("초당 글자수(CPS) 상한 — 낮을수록 천천히 읽힘")
            read_row.addWidget(QLabel("한 줄 글자수"))
            read_row.addWidget(self._maxchars_spin)
            read_row.addSpacing(12)
            read_row.addWidget(QLabel("CPS 상한"))
            read_row.addWidget(self._maxcps_spin)
            read_row.addStretch(1)
            read_wrap = QWidget()
            read_wrap.setLayout(read_row)
            form.addRow("가독성", read_wrap)

            self._audio_enhance_check = QCheckBox("노이즈 제거 · 음량 정규화 (권장)")
            self._audio_enhance_check.setChecked(True)
            self._audio_enhance_check.setToolTip(
                "잡음이 많거나 음량이 들쭉날쭉한 영상의 인식률을 높입니다. 깨끗한 스튜디오 "
                "녹음이면 꺼도 됩니다."
            )
            form.addRow("오디오 향상", self._audio_enhance_check)

            self._translate_combo = QComboBox()
            self._translate_combo.addItems(_TRANSLATE_LANGS)
            form.addRow("번역 대상", self._translate_combo)

            self._preset_combo = QComboBox()
            self._preset_combo.addItem("(없음)")
            for name in self._available_presets():
                self._preset_combo.addItem(name)
            form.addRow("스타일 프리셋", self._preset_combo)

            fmt_row = QHBoxLayout()
            fmt_row.setSpacing(14)
            self._srt_check = QCheckBox("SRT")
            self._srt_check.setChecked(True)
            self._vtt_check = QCheckBox("VTT")
            fmt_row.addWidget(self._srt_check)
            fmt_row.addWidget(self._vtt_check)
            fmt_row.addStretch(1)
            fmt_wrap = QWidget()
            fmt_wrap.setLayout(fmt_row)
            form.addRow("출력 포맷", fmt_wrap)

            v.addLayout(form)
            return card

        def _available_presets(self) -> list[str]:
            """엔진에서 사용 가능한 스타일 프리셋 목록을 얻는다(실패 시 빈 목록)."""
            try:
                from volo_engine.style import list_presets

                return list_presets()
            except Exception:
                return []

        # ---------------- 실행 카드 (생성 버튼 + 진행률) ---------------- #
        def _build_run_card(self) -> QFrame:
            card, v = self._make_card("생성")

            self._generate_btn = QPushButton("✨  자막 생성")
            self._generate_btn.setObjectName("primary")
            self._generate_btn.setMinimumHeight(44)
            self._generate_btn.clicked.connect(self._on_generate)
            self._generate_btn.setEnabled(False)
            v.addWidget(self._generate_btn)

            self._progress = QProgressBar()
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
            v.addWidget(self._progress)

            self._status = QLabel("영상을 추가하면 자막 생성을 시작할 수 있습니다.")
            self._status.setObjectName("muted")
            v.addWidget(self._status)
            return card

        # ---------------- 미리보기 카드 ---------------- #
        def _build_preview_card(self) -> QFrame:
            card, v = self._make_card("자막 미리보기 / 편집  ·  텍스트 칸을 더블클릭해 수정")

            self._table = QTableWidget(0, 4)
            self._table.setHorizontalHeaderLabels(["#", "시작", "끝", "자막 텍스트"])
            header = self._table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            self._table.verticalHeader().setVisible(False)
            self._table.setAlternatingRowColors(False)
            self._table.setMinimumHeight(240)
            v.addWidget(self._table)
            return card

        # ---------------- 출력/내보내기 행 ---------------- #
        def _build_export_row(self) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setSpacing(10)
            self._out_btn = QPushButton("📁  출력 폴더")
            self._out_btn.clicked.connect(self._on_pick_out_dir)
            self._out_label = QLabel("출력 폴더: 입력 파일과 동일")
            self._out_label.setObjectName("muted")

            self._export_btn = QPushButton("💾  편집본 내보내기")
            self._export_btn.clicked.connect(self._on_export_edits)
            self._export_btn.setEnabled(False)

            row.addWidget(self._out_btn)
            row.addWidget(self._out_label, 1)
            row.addWidget(self._export_btn)
            return row

        # =================== 이벤트 핸들러 =================== #
        def _on_files_selected(self, paths: list[str]) -> None:
            """드롭/선택된 파일 처리(현재 MVP: 첫 파일만 사용. 배치는 향후)."""
            valid = [p for p in paths if os.path.splitext(p)[1].lower() in _MEDIA_EXTS]
            if not valid:
                QMessageBox.warning(
                    self, "지원하지 않는 파일",
                    "영상/오디오 파일(mp4, mov, mkv, wav 등)을 선택하세요.",
                )
                return
            self._video_path = valid[0]
            name = os.path.basename(self._video_path)
            extra = f"   (외 {len(valid) - 1}개는 무시 — 배치는 향후 지원)" if len(valid) > 1 else ""
            self._file_label.setText(f"🎞  {name}{extra}")
            self._generate_btn.setEnabled(True)
            self._status.setText("준비 완료 — [자막 생성]을 누르세요.")

        def _on_pick_glossary(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, "글로서리 JSON 선택", "", "JSON (*.json);;모든 파일 (*.*)"
            )
            if path:
                self._glossary_path = path
                self._glossary_label.setText(os.path.basename(path))

        def _on_clear_glossary(self) -> None:
            self._glossary_path = None
            self._glossary_label.setText("(선택 안 함)")

        def _on_pick_out_dir(self) -> None:
            chosen = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
            if chosen:
                self._out_dir = chosen
                self._out_label.setText(f"출력 폴더: {chosen}")

        def _selected_formats(self) -> list[str]:
            fmts: list[str] = []
            if self._srt_check.isChecked():
                fmts.append("srt")
            if self._vtt_check.isChecked():
                fmts.append("vtt")
            return fmts or ["srt"]

        def _load_glossary_safe(self) -> dict[str, str] | None:
            """선택된 글로서리 JSON 을 ``{원표기: 교정표기}`` 로 로드한다(실패 시 경고 후 None)."""
            if not self._glossary_path:
                return None
            try:
                with open(self._glossary_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
                raise ValueError('JSON 객체 형식이어야 합니다: {"원표기":"교정표기"}')
            except Exception as exc:  # noqa: BLE001 - 사용자에게 그대로 보고
                QMessageBox.warning(self, "글로서리 로드 실패", f"{exc}")
                return None

        def _build_options(self) -> Any:
            """UI 입력 → :class:`volo_engine.pipeline.PipelineOptions` 로 변환."""
            from volo_engine.config import default_segment_rules
            from volo_engine.pipeline import PipelineOptions

            lang_text = self._lang_edit.text().strip()
            language = lang_text or None  # 비우면 자동감지(None)

            translate_to = self._translate_combo.currentText()
            translate_to = None if translate_to == "(없음)" else translate_to

            preset = self._preset_combo.currentText()
            preset = None if preset == "(없음)" else preset

            rules = default_segment_rules()
            rules.max_chars_per_line = self._maxchars_spin.value()
            rules.max_cps = self._maxcps_spin.value()

            prompt = self._prompt_edit.text().strip() or None

            return PipelineOptions(
                model_size=self._model_combo.currentText(),
                language=language,
                glossary=self._load_glossary_safe(),
                prompt=prompt,
                rules=rules,
                translate_to=translate_to,
                preset=preset,
                formats=self._selected_formats(),
                device=self._device_combo.currentData(),
                denoise=self._audio_enhance_check.isChecked(),
                normalize=self._audio_enhance_check.isChecked(),
                out_dir=self._out_dir,
            )

        def _on_generate(self) -> None:
            if not self._video_path:
                return

            options = self._build_options()

            # 번역 백엔드 미주입 경고(모킹 금지 — 엔진이 명확한 오류를 던진다).
            if options.translate_to and options.translate_backend is None:
                proceed = QMessageBox.question(
                    self, "번역 백엔드 없음",
                    "번역 대상 언어를 선택했지만 번역 백엔드가 연결되어 있지 않습니다.\n"
                    "엔진은 번역 단계에서 오류를 냅니다(가짜 통과 없음).\n\n"
                    "번역 없이 진행하려면 '번역 대상'을 (없음)으로 두세요.\n그래도 시도할까요?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if proceed != QMessageBox.StandardButton.Yes:
                    return

            self._set_busy(True)
            self._progress.setValue(0)
            self._status.setText("시작 중…")
            self._table.setRowCount(0)
            self._last_result = None

            # 워커 스레드 구성 ----------------------------------------------- #
            from .worker import PipelineWorker

            self._thread = QThread(self)
            self._worker = PipelineWorker(self._video_path, options)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.progress.connect(self._on_progress)
            self._worker.finished.connect(self._on_finished)
            self._worker.failed.connect(self._on_failed)
            self._worker.done.connect(self._thread.quit)
            self._worker.done.connect(self._worker.deleteLater)
            self._thread.finished.connect(self._thread.deleteLater)
            self._thread.finished.connect(self._on_thread_finished)
            self._thread.start()

        def _on_progress(self, label: str, percent: int) -> None:
            self._progress.setValue(percent)
            self._status.setText(f"{label} … {percent}%")

        def _on_finished(self, result: object) -> None:
            self._last_result = dict(result) if isinstance(result, dict) else None
            self._progress.setValue(100)
            res = self._last_result or {}
            paths = res.get("output_paths", [])
            cps_over = res.get("cps_over_count", 0)
            msg = f"완료 — 파일 {len(paths)}개 생성. 아래 표에서 확인/편집하세요."
            if cps_over:
                msg += f"   ⚠ {cps_over}개 cue 가독속도(CPS) 초과"
            self._status.setText(msg)
            self._load_preview(self._last_result)
            self._export_btn.setEnabled(self._table.rowCount() > 0)

        def _on_failed(self, user_msg: str, detail: str) -> None:
            self._status.setText("실패")
            self._progress.setValue(0)
            dlg = QMessageBox(self)
            dlg.setIcon(QMessageBox.Icon.Critical)
            dlg.setWindowTitle("자막 생성 실패")
            dlg.setText(user_msg)
            dlg.setDetailedText(detail)
            dlg.exec()

        def _on_thread_finished(self) -> None:
            self._thread = None
            self._worker = None
            self._set_busy(False)

        # =================== 미리보기 / 편집 / 내보내기 =================== #
        def _preview_source_path(self, result: dict[str, Any] | None) -> str | None:
            """미리보기로 읽을 자막 파일 경로를 고른다(원본 언어 SRT 우선)."""
            if not result:
                return None
            by_fmt = result.get("outputs_by_format", {}) or {}
            # 키 형식: "srt:src", "vtt:en" 등. 원본(src) SRT → 원본 VTT → 아무거나.
            for key in ("srt:src", "vtt:src"):
                if key in by_fmt:
                    return by_fmt[key]
            for key, path in by_fmt.items():
                if key.endswith(":src"):
                    return path
            paths = result.get("output_paths", []) or []
            for p in paths:
                if p.lower().endswith((".srt", ".vtt")):
                    return p
            return None

        def _load_preview(self, result: dict[str, Any] | None) -> None:
            """생성된 자막 파일을 파싱해 미리보기 테이블을 채운다."""
            path = self._preview_source_path(result)
            self._preview_path = path
            self._table.setRowCount(0)
            if not path or not os.path.isfile(path):
                return
            self._populate_table(parse_subtitle_file(path))

        def _populate_table(self, rows: list[CueRow]) -> None:
            """cue 행 리스트로 미리보기 테이블을 채운다(샘플/실데이터 공용)."""
            self._table.setRowCount(len(rows))
            for r, cue in enumerate(rows):
                idx_item = QTableWidgetItem(str(cue.index))
                idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                start_item = QTableWidgetItem(seconds_to_srt_tc(cue.start))
                end_item = QTableWidgetItem(seconds_to_srt_tc(cue.end))
                # 시작/끝은 편집 비활성(MVP: 텍스트 인라인 편집만. 타임 편집은 향후).
                start_item.setFlags(start_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                end_item.setFlags(end_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                text_item = QTableWidgetItem(cue.text)
                # 원본 초 값을 데이터로 보존(재내보내기 시 사용).
                text_item.setData(Qt.ItemDataRole.UserRole, (cue.start, cue.end))
                self._table.setItem(r, 0, idx_item)
                self._table.setItem(r, 1, start_item)
                self._table.setItem(r, 2, end_item)
                self._table.setItem(r, 3, text_item)

        def load_sample_preview(self) -> None:
            """데모/스크린샷용 샘플 자막을 미리보기에 채운다(엔진 호출 없음)."""
            rows = [
                CueRow(1, 0.40, 2.60, "안녕하세요, 볼로 데모 영상입니다"),
                CueRow(2, 2.80, 5.40, "AI가 음성을 듣고 자막을 자동으로 만듭니다"),
                CueRow(3, 5.60, 8.20, "한국어 줄바꿈과 타이밍까지\n가독성 기준으로 맞춰줍니다"),
                CueRow(4, 8.40, 10.90, "완성된 자막은 SRT로 내보내\n프리미어에 바로 임포트하세요"),
            ]
            self._populate_table(rows)
            # 데모 표현: 선택 파일/생성 버튼을 '준비됨' 상태로 보여 강조 버튼을 노출.
            self._file_label.setText("🎞  sample_interview.mp4")
            self._generate_btn.setEnabled(True)
            self._export_btn.setEnabled(True)
            self._status.setText("샘플 미리보기 (데모) — 실제 생성은 영상을 넣고 [자막 생성].")
            self._progress.setValue(100)

        def _collect_edited_subtitles(self) -> list[Any]:
            """테이블의 (편집된) 행들을 :class:`volo_engine.models.Subtitle` 리스트로 만든다."""
            from volo_engine.models import Subtitle

            subs: list[Any] = []
            for r in range(self._table.rowCount()):
                text_item = self._table.item(r, 3)
                if text_item is None:
                    continue
                start, end = text_item.data(Qt.ItemDataRole.UserRole)
                lines = [ln for ln in text_item.text().split("\n") if ln.strip() != ""]
                if not lines:
                    lines = [""]
                subs.append(
                    Subtitle(index=r + 1, start=float(start), end=float(end), lines=lines)
                )
            return subs

        def _on_export_edits(self) -> None:
            """편집된 cue 를 엔진 export 로 다시 내보낸다(공개 함수 직접 호출)."""
            if self._table.rowCount() == 0:
                return
            try:
                from volo_engine import export as export_mod
            except Exception as exc:
                QMessageBox.critical(self, "내보내기 실패", f"엔진을 불러올 수 없습니다: {exc}")
                return

            subtitles = self._collect_edited_subtitles()

            base_path = self._preview_path
            if not base_path:
                QMessageBox.warning(self, "내보내기", "먼저 자막을 생성하세요.")
                return
            out_dir = self._out_dir or os.path.dirname(base_path)
            stem = os.path.splitext(os.path.basename(base_path))[0]

            written: list[str] = []
            try:
                for fmt in self._selected_formats():
                    out_path = os.path.join(out_dir, f"{stem}.edited.{fmt}")
                    written.append(export_mod.export(subtitles, fmt, out_path))
            except Exception as exc:
                user = getattr(exc, "user_message", None)
                msg = user() if callable(user) else str(exc)
                QMessageBox.critical(self, "내보내기 실패", msg)
                return

            self._status.setText(f"내보내기 완료 — {len(written)}개 파일")
            files = "\n".join(written)
            QMessageBox.information(
                self, "내보내기 완료",
                "편집된 자막을 저장했습니다:\n\n"
                f"{files}\n\n"
                "프리미어에서 [파일 → 가져오기]로 .srt 를 불러오면 캡션 트랙이 생성됩니다.",
            )

        # =================== 상태 토글 =================== #
        def _set_busy(self, busy: bool) -> None:
            """생성 중에는 옵션/생성 버튼을 잠그고 진행 표시만 활성."""
            self._generate_btn.setEnabled(not busy and self._video_path is not None)
            for w in (
                self._drop, self._model_combo, self._lang_edit, self._device_combo,
                self._prompt_edit, self._gloss_btn, self._gloss_clear,
                self._maxchars_spin, self._maxcps_spin, self._audio_enhance_check,
                self._translate_combo,
                self._preset_combo, self._srt_check, self._vtt_check, self._out_btn,
            ):
                w.setEnabled(not busy)
            if busy:
                self._export_btn.setEnabled(False)
