"""CampusNet's first cross-platform desktop UI prototype.

Run from a development environment with `python -m campusnet.gui`.
The GUI wraps the existing authentication engine; it does not claim to be a
production installer yet.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import replace
from html import escape
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt
from PySide6.QtGui import QAction, QColor, QCloseEvent, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyle,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .autostart import is_enabled, set_enabled
from .config import AppConfig, load_config, validate_portal_base_url, write_config
from .credentials import CredentialError, load_credentials, save_credentials


APP_TITLE = "CampusNet"
ASSET_DIR = Path(__file__).resolve().parent / "assets"
APP_ICON_PATH = ASSET_DIR / "campusnet-app-icon.png"
# A pre-scaled copy of the 1024x1024 app icon. Window, tray and header icons are
# never larger than 128px, so decoding the full-size PNG for them is wasted work.
# The full-size PNG and campusnet.ico are kept for packaging and other platforms.
SMALL_ICON_PATH = ASSET_DIR / "campusnet-app-icon-128.png"
MARK_ICON_PATH = ASSET_DIR / "campusnet-mark.png"


# Name of the local socket used to detect an instance that is already running.
SINGLE_INSTANCE_KEY = "CampusNet-desktop-single-instance"


def _claim_single_instance():
    """Claim the single-instance lock for this process.

    Returns ``(already_running, server)``. If another instance is already
    listening it is asked to show its window and ``already_running`` is True, so
    this process should exit instead of starting a second copy that would poll
    and authenticate against the same portal session. If the lock cannot be
    claimed at all, both values are falsy and startup continues unguarded rather
    than refusing to run.
    """
    # Imported here so the path that runs before the window stays small.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(500):
        probe.write(b"show")
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return True, None

    # Nothing answered, so any socket with this name was left behind by a crash.
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    if not server.listen(SINGLE_INSTANCE_KEY):
        return False, None
    return False, server


def _campusnet_icon() -> QIcon:
    """Load the bundled CampusNet icon, with a safe fallback for source checkouts."""
    for path in (SMALL_ICON_PATH, APP_ICON_PATH, MARK_ICON_PATH):
        if path.is_file():
            return QIcon(str(path))
    return QIcon()


MESSAGE_DIALOG_STYLE = """
    QDialog#campusMessageDialog {
        background-color: #f4f7fb;
        color: #101828;
    }
    QLabel#messageDialogTitle {
        background: transparent;
        color: #101828;
        font-size: 16px;
        font-weight: 700;
    }
    QLabel#messageDialogBody {
        background: transparent;
        color: #475467;
        font-size: 12px;
    }
    QLabel#messageDialogIcon {
        border-radius: 18px;
        font-size: 18px;
        font-weight: 800;
    }
    QPushButton#dialogPrimaryButton {
        background-color: #1d4ed8;
        color: #ffffff;
        border: 1px solid #1d4ed8;
        border-radius: 8px;
        padding: 9px 18px;
        min-width: 76px;
        min-height: 18px;
        font-weight: 600;
    }
    QPushButton#dialogPrimaryButton:hover {
        background-color: #1e40af;
        border-color: #1e40af;
    }
    QPushButton#dialogSecondaryButton {
        background-color: #ffffff;
        color: #344054;
        border: 1px solid #d0d5dd;
        border-radius: 8px;
        padding: 9px 18px;
        min-width: 76px;
        min-height: 18px;
        font-weight: 600;
    }
    QPushButton#dialogSecondaryButton:hover {
        background-color: #eff6ff;
        border-color: #93c5fd;
    }
"""


class CampusMessageDialog(QDialog):
    """Compact, consistently styled confirmation dialog independent of OS theme."""

    def __init__(
        self,
        parent: QWidget | None,
        icon: QMessageBox.Icon,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        default_button: QMessageBox.StandardButton | None = None,
    ) -> None:
        super().__init__(parent)
        self.choice = QMessageBox.StandardButton.NoButton
        self.setObjectName("campusMessageDialog")
        self.setWindowTitle(title)
        self.setWindowIcon(_campusnet_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.setFixedWidth(460)
        self.setStyleSheet(MESSAGE_DIALOG_STYLE)

        icon_styles = {
            QMessageBox.Icon.Information: ("i", "#dbeafe", "#1d4ed8"),
            QMessageBox.Icon.Warning: ("!", "#fef3c7", "#b45309"),
            QMessageBox.Icon.Critical: ("!", "#fee2e2", "#b42318"),
            QMessageBox.Icon.Question: ("?", "#e0e7ff", "#4338ca"),
        }
        symbol, icon_bg, icon_fg = icon_styles.get(icon, icon_styles[QMessageBox.Icon.Information])

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        heading = QHBoxLayout()
        heading.setSpacing(12)
        icon_label = QLabel(symbol)
        icon_label.setObjectName("messageDialogIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(36, 36)
        icon_label.setStyleSheet(
            f"background-color: {icon_bg}; color: {icon_fg};"
        )
        heading.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        title_label = QLabel(title)
        title_label.setObjectName("messageDialogTitle")
        title_label.setWordWrap(True)
        heading.addWidget(title_label, 1, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(heading)

        body_label = QLabel(text)
        body_label.setObjectName("messageDialogBody")
        body_label.setWordWrap(True)
        body_label.setTextFormat(Qt.TextFormat.PlainText)
        body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(body_label)

        button_flags = QDialogButtonBox.StandardButton(buttons.value)
        self.button_box = QDialogButtonBox(button_flags, Qt.Orientation.Horizontal, self)
        self.button_box.setCenterButtons(False)
        for button in self.button_box.buttons():
            standard_button = self.button_box.standardButton(button)
            if standard_button in (
                QDialogButtonBox.StandardButton.Ok,
                QDialogButtonBox.StandardButton.Yes,
                QDialogButtonBox.StandardButton.Save,
                QDialogButtonBox.StandardButton.Apply,
            ):
                button.setObjectName("dialogPrimaryButton")
            else:
                button.setObjectName("dialogSecondaryButton")
            button.setAutoDefault(False)
            button.setDefault(False)
            button.clicked.connect(lambda _checked=False, clicked=button: self._choose(clicked))

        root.addWidget(self.button_box, 0, Qt.AlignmentFlag.AlignRight)

        if default_button is not None:
            default_widget = self.button_box.button(QDialogButtonBox.StandardButton(default_button.value))
        else:
            default_widget = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
            if default_widget is None:
                default_widget = self.button_box.button(QDialogButtonBox.StandardButton.Yes)
        if default_widget is not None:
            default_widget.setDefault(True)
            default_widget.setAutoDefault(True)

        # Let wrapped body text determine a compact height while keeping the width stable.
        self.adjustSize()

    def _choose(self, button: QPushButton) -> None:
        standard_button = self.button_box.standardButton(button)
        try:
            self.choice = QMessageBox.StandardButton(standard_button.value)
        except (AttributeError, ValueError):
            self.choice = QMessageBox.StandardButton.NoButton
        self.accept()


def _create_message_dialog(
    parent: QWidget | None,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton | None = None,
) -> CampusMessageDialog:
    """Build a compact app-styled dialog with predictable layout and contrast."""
    return CampusMessageDialog(parent, icon, title, text, buttons, default_button)


def _show_message(
    parent: QWidget | None,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton | None = None,
) -> QMessageBox.StandardButton:
    dialog = _create_message_dialog(parent, icon, title, text, buttons, default_button)
    dialog.exec()
    return dialog.choice


def _show_warning(parent: QWidget | None, title: str, text: str) -> QMessageBox.StandardButton:
    return _show_message(parent, QMessageBox.Icon.Warning, title, text)


def _show_critical(parent: QWidget | None, title: str, text: str) -> QMessageBox.StandardButton:
    return _show_message(parent, QMessageBox.Icon.Critical, title, text)


def _show_information(parent: QWidget | None, title: str, text: str) -> QMessageBox.StandardButton:
    return _show_message(parent, QMessageBox.Icon.Information, title, text)


class QtLogHandler(logging.Handler):
    """Forward backend log records safely to the Qt UI thread."""

    def __init__(self, emit_line):
        super().__init__()
        self.emit_line = emit_line
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emit_line(self.format(record))
        except RuntimeError:
            # The UI may already be closing while the worker is finishing.
            pass


class BackendWorker(QThread):
    log_line = Signal(str)
    state_changed = Signal(str, str)
    stopped = Signal()
    failed = Signal(str)

    def __init__(self, config: AppConfig, parent: QObject | None = None):
        super().__init__(parent)
        self.config = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._logger = logging.getLogger("campusnet")
        self._handler = QtLogHandler(self._on_log)

    def _on_log(self, message: str) -> None:
        self.log_line.emit(message)
        lower = message.lower()
        if "login form detected" in lower or "submitting credentials" in lower:
            self.state_changed.emit("Signing in", "working")
        elif "authenticated keepalive page detected" in lower or "portal flow completed" in lower:
            self.state_changed.emit("Connected · monitoring session", "connected")
        elif "internet access has recovered" in lower or "portal authentication/keepalive was refreshed" in lower:
            self.state_changed.emit("Connected · session recovered", "connected")
        elif "fresh portal url detected" in lower or "fresh portal redirect" in lower:
            self.state_changed.emit("Captive portal detected · connecting", "working")
        elif "connectivity check failed" in lower or "trying chromium-based" in lower or "no fresh fortigate redirect" in lower:
            self.state_changed.emit("Checking connection · recovering if needed", "working")
        elif "needs attention" in lower or "could not open the portal" in lower:
            self.state_changed.emit("Needs attention", "error")
        elif "internet is already available" in lower:
            self.state_changed.emit("Internet available · monitoring", "connected")

    def run(self) -> None:
        # Imported here, not at module scope: the event loop is only ever needed
        # on this worker thread, and the import is off the pre-window path.
        import asyncio

        self._logger.addHandler(self._handler)
        self._logger.setLevel(logging.INFO)
        try:
            async def worker_main() -> None:
                self._loop = asyncio.get_running_loop()
                self._stop_event = asyncio.Event()
                # Import Playwright/httpx only on the background thread. This keeps
                # the dashboard responsive while the browser engine initializes.
                from .monitor import run_app

                await run_app(replace(self.config, headless=True), show_browser=False, stop_event=self._stop_event)

            asyncio.run(worker_main())
        except CredentialError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"CampusNet stopped unexpectedly: {exc}")
        finally:
            self._logger.removeHandler(self._handler)
            self.stopped.emit()

    def request_stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)


class SetupDialog(QDialog):
    """First-run/settings dialog with clear, grouped setup fields."""

    def __init__(self, config: AppConfig | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("CampusNet setup")
        self.setWindowIcon(_campusnet_icon())
        self.setMinimumWidth(560)
        self.saved_config: AppConfig | None = None

        try:
            existing_username, _ = load_credentials()
        except CredentialError:
            existing_username = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(15)

        title = QLabel("Connect CampusNet")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "Set up your college portal once. CampusNet keeps your password in your "
            "operating system's secure credential store."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        section = QLabel("NETWORK DETAILS")
        section.setObjectName("eyebrow")
        root.addWidget(section)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # First-time users often don't know which of the portal's changing URLs
        # belongs here. Keep this explanation immediately above the URL field.
        self.portal_url_hint = QLabel(
            "First time? Connect to campus Wi-Fi/LAN, open the page that asks for your "
            "college username and password, then copy its address from the browser bar. "
            "Use that login page—not the post-login Authentication Keepalive page. "
            "If the address contains a ? followed by a long code, remove the ? and "
            "everything after it. Example format: https://portal.yourcollege.edu/fgtauth "
            "(your college's address will differ)."
        )
        self.portal_url_hint.setObjectName("portalUrlHint")
        self.portal_url_hint.setWordWrap(True)
        form.addRow(self.portal_url_hint)

        self.portal_input = QLineEdit(config.portal_url if config else "")
        self.portal_input.setPlaceholderText("https://portal.yourcollege.edu/fgtauth")
        self.portal_input.setClearButtonEnabled(True)
        self.username_input = QLineEdit(existing_username)
        self.username_input.setPlaceholderText("Your college username")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter password to save or change it")
        form.addRow("Portal login URL", self.portal_input)
        form.addRow("Username", self.username_input)

        password_row = QWidget()
        password_layout = QHBoxLayout(password_row)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(8)
        password_layout.addWidget(self.password_input, 1)
        self.show_password = QCheckBox("Show")
        self.show_password.toggled.connect(
            lambda visible: self.password_input.setEchoMode(
                QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
            )
        )
        password_layout.addWidget(self.show_password)
        form.addRow("Password", password_row)
        root.addLayout(form)

        hint = QLabel("Leave password blank to keep the previously saved password.")
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        root.addWidget(hint)

        security_card = QFrame()
        security_card.setObjectName("securityCard")
        security_layout = QVBoxLayout(security_card)
        security_layout.setContentsMargins(14, 12, 14, 12)
        security_layout.setSpacing(6)
        security_title = QLabel("Portal certificate")
        security_title.setObjectName("securityTitle")
        self.ignore_tls = QCheckBox("Allow an untrusted certificate for this portal")
        self.ignore_tls.setChecked(config.ignore_portal_tls_errors if config else False)
        security_note = QLabel(
            "Only enable this if your college IT team confirms the warning is expected. "
            "It weakens protection for your login credentials. CampusNet applies this option "
            "to its portal browser only; it is off by default."
        )
        security_note.setObjectName("securityNote")
        security_note.setWordWrap(True)
        security_layout.addWidget(security_title)
        security_layout.addWidget(self.ignore_tls)
        security_layout.addWidget(security_note)
        root.addWidget(security_card)

        self.autostart = QCheckBox("Launch at startup")
        self.autostart.setToolTip("Starts CampusNet automatically when you sign in to this computer.")
        self.autostart.setChecked(config.launch_at_startup if config is not None else True)
        root.addWidget(self.autostart)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save settings")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.setStyleSheet("""
            QDialog { background: #f5f7fb; }
            QLabel { color: #172033; }
            QLabel#dialogTitle { color: #101828; font-size: 23px; font-weight: 750; }
            QLabel#dialogSubtitle { color: #667085; font-size: 12px; }
            QLabel#eyebrow { color: #667085; font-size: 10px; font-weight: 750; letter-spacing: 1px; }
            QLabel#helperText { color: #667085; font-size: 11px; }
            QLabel#portalUrlHint { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 10px 12px; font-size: 11px; }
            QLabel#securityTitle { color: #92400e; font-weight: 700; }
            QLabel#securityNote { color: #92400e; font-size: 11px; }
            QFrame#securityCard { background: #fff7ed; border: 1px solid #fed7aa; border-radius: 10px; }
            QLineEdit { color: #101828; min-height: 20px; padding: 9px 10px; border: 1px solid #d0d5dd; border-radius: 7px; background: #ffffff; selection-color: #101828; selection-background-color: #bfdbfe; }
            QLineEdit:focus { color: #101828; background: #ffffff; border: 1px solid #3b82f6; }
            QLineEdit:disabled { color: #667085; background: #f2f4f7; }
            QCheckBox { spacing: 8px; color: #344054; }
            QPushButton { min-height: 18px; padding: 8px 14px; border: 1px solid #d0d5dd; border-radius: 7px; background: white; color: #344054; }
            QPushButton:hover { background: #eff6ff; }
            QPushButton:default { background: #1d4ed8; color: white; border: 1px solid #1d4ed8; font-weight: 650; }
        """)

        # Do not rely on the operating system's default palette: on some Windows
        # dark-theme configurations that palette can make text white on our white
        # input backgrounds. Force readable foreground, placeholder, and selection
        # colors for all credential/configuration fields.
        for field in (self.portal_input, self.username_input, self.password_input):
            field_palette = field.palette()
            field_palette.setColor(QPalette.ColorRole.Text, QColor("#101828"))
            field_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#667085"))
            field_palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
            field_palette.setColor(QPalette.ColorRole.Highlight, QColor("#bfdbfe"))
            field_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#101828"))
            field.setPalette(field_palette)

    def _save(self) -> None:
        portal = self.portal_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not portal or not username:
            _show_warning(self, "Missing information", "Portal URL and username are required.")
            return
        try:
            portal = validate_portal_base_url(portal)
            current_username, _ = load_credentials()
            has_saved_credentials = True
        except CredentialError:
            current_username = ""
            has_saved_credentials = False
        except ValueError as exc:
            _show_warning(self, "Invalid portal URL", str(exc))
            return

        if password:
            try:
                save_credentials(username, password)
            except (CredentialError, ValueError) as exc:
                _show_critical(self, "Could not save credentials", str(exc))
                return
        elif not has_saved_credentials or username != current_username:
            _show_warning(
                self,
                "Password required",
                "Enter the password when setting up a new account or changing the username.",
            )
            return

        try:
            base = AppConfig(portal_url=portal)
            self.saved_config = AppConfig(
                portal_url=base.portal_url,
                keepalive_path=base.keepalive_path,
                keepalive_success_text=base.keepalive_success_text,
                username_selector=base.username_selector,
                password_selector=base.password_selector,
                submit_selector=base.submit_selector,
                connectivity_url=base.connectivity_url,
                expected_status=base.expected_status,
                check_interval_seconds=base.check_interval_seconds,
                retry_delay_seconds=base.retry_delay_seconds,
                request_timeout_seconds=base.request_timeout_seconds,
                headless=True,
                ignore_portal_tls_errors=self.ignore_tls.isChecked(),
                launch_at_startup=self.autostart.isChecked(),
            )
            write_config(self.saved_config)
            set_enabled(self.autostart.isChecked())
        except Exception as exc:
            _show_critical(self, "Setup failed", f"CampusNet could not save settings:\n{exc}")
            return
        self.accept()


class MainWindow(QMainWindow):
    """A calmer dashboard intended for everyday users, not just debugging."""

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.worker: BackendWorker | None = None
        self._allow_close = False
        self._tray_notice_shown = False
        self._current_status_kind = "working"
        self._setup_retry_done = False
        self.setWindowTitle(f"CampusNet · v{__version__}")
        self.setWindowIcon(_campusnet_icon())
        self.setMinimumSize(780, 600)
        self.resize(930, 700)

        central = QWidget()
        central.setObjectName("page")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(28, 24, 28, 22)
        outer.setSpacing(16)

        # Brand header
        header = QHBoxLayout()
        header.setSpacing(12)
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(56, 56)
        mark_source = SMALL_ICON_PATH if SMALL_ICON_PATH.is_file() else APP_ICON_PATH
        if mark_source.is_file():
            mark.setPixmap(
                QPixmap(str(mark_source)).scaled(
                    mark.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        header.addWidget(mark)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)
        title = QLabel("CampusNet")
        title.setObjectName("brandTitle")
        subtitle = QLabel("Your campus connection, handled automatically")
        subtitle.setObjectName("brandSubtitle")
        brand_col.addWidget(title)
        brand_col.addWidget(subtitle)
        header.addLayout(brand_col, 1)

        self.settings_button = QPushButton("Settings")
        self.settings_button.setObjectName("secondaryButton")
        self.settings_button.clicked.connect(self.edit_settings)
        header.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(header)

        # Main status card
        status_card = QFrame()
        status_card.setObjectName("statusCard")
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(20, 19, 20, 19)
        status_layout.setSpacing(16)

        self.status_icon = QLabel("…")
        self.status_icon.setObjectName("statusIcon")
        self.status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_icon.setFixedSize(48, 48)
        status_layout.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)

        copy_col = QVBoxLayout()
        copy_col.setSpacing(5)
        status_top = QHBoxLayout()
        self.status_badge = QLabel("STARTING")
        self.status_badge.setObjectName("statusBadge")
        status_top.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignLeft)
        status_top.addStretch(1)
        copy_col.addLayout(status_top)
        self.status_text = QLabel("Starting CampusNet")
        self.status_text.setObjectName("statusTitle")
        self.status_text.setWordWrap(True)
        self.status_detail = QLabel("Checking your campus internet connection.")
        self.status_detail.setObjectName("statusDetail")
        self.status_detail.setWordWrap(True)
        copy_col.addWidget(self.status_text)
        copy_col.addWidget(self.status_detail)
        status_layout.addLayout(copy_col, 1)

        controls = QVBoxLayout()
        controls.addStretch(1)
        self.toggle_monitoring_button = QPushButton("Pause monitoring")
        self.toggle_monitoring_button.setObjectName("primaryButton")
        self.toggle_monitoring_button.clicked.connect(self.toggle_monitoring)
        controls.addWidget(self.toggle_monitoring_button)
        controls.addStretch(1)
        status_layout.addLayout(controls)
        outer.addWidget(status_card)

        # Features are framed as outcomes, not internal implementation details.
        section_heading = QLabel("WHAT CAMPUSNET HANDLES")
        section_heading.setObjectName("eyebrow")
        outer.addWidget(section_heading)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.feature_cards: list[QFrame] = []
        for symbol, title_text, description in [
            ("↻", "Automatic sign-in", "Uses your saved college credentials when the portal asks you to sign in."),
            ("◷", "Session monitoring", "Keeps an eye on connectivity and the portal session."),
            ("✓", "Recovery", "Attempts to restore authentication if it expires."),
        ]:
            card = QFrame()
            card.setObjectName("featureCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 14, 15, 14)
            card_layout.setSpacing(7)
            symbol_label = QLabel(symbol)
            symbol_label.setObjectName("featureSymbol")
            title_label = QLabel(title_text)
            title_label.setObjectName("featureTitle")
            detail_label = QLabel(description)
            detail_label.setObjectName("featureDetail")
            detail_label.setWordWrap(True)
            card_layout.addWidget(symbol_label)
            card_layout.addWidget(title_label)
            card_layout.addWidget(detail_label, 1)
            cards.addWidget(card, 1)
            self.feature_cards.append(card)
        outer.addLayout(cards)

        # Keep logs available but hidden by default so the app is not intimidating.
        activity_card = QFrame()
        activity_card.setObjectName("activityCard")
        activity_layout = QVBoxLayout(activity_card)
        activity_layout.setContentsMargins(17, 15, 17, 15)
        activity_layout.setSpacing(10)

        activity_header = QHBoxLayout()
        activity_title_col = QVBoxLayout()
        activity_title_col.setSpacing(3)
        activity_title = QLabel("Recent activity")
        activity_title.setObjectName("sectionTitle")
        activity_subtitle = QLabel("CampusNet's latest status update")
        activity_subtitle.setObjectName("mutedText")
        activity_title_col.addWidget(activity_title)
        activity_title_col.addWidget(activity_subtitle)
        activity_header.addLayout(activity_title_col, 1)
        self.details_button = QPushButton("View technical log")
        self.details_button.setObjectName("linkButton")
        self.details_button.clicked.connect(self.toggle_activity_details)
        activity_header.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignVCenter)
        activity_layout.addLayout(activity_header)

        self.activity_preview = QLabel("Waiting for the first status update…")
        self.activity_preview.setObjectName("activityPreview")
        self.activity_preview.setWordWrap(True)
        activity_layout.addWidget(self.activity_preview)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Detailed diagnostic messages will appear here.")
        self.log_view.setObjectName("logView")
        self.log_view.setMinimumHeight(170)
        self.log_view.setMaximumHeight(240)
        self.log_view.document().setMaximumBlockCount(300)
        self.log_view.hide()
        activity_layout.addWidget(self.log_view)
        outer.addWidget(activity_card, 1)

        # Quiet, secondary controls
        footer = QHBoxLayout()
        self.startup_checkbox = QCheckBox("Launch at startup")
        self.startup_checkbox.setObjectName("startupCheckbox")
        self.startup_checkbox.setToolTip("Starts CampusNet automatically when you sign in to this computer.")
        self.startup_checkbox.setChecked(self.config.launch_at_startup)
        self.startup_checkbox.toggled.connect(self._change_autostart)
        footer.addWidget(self.startup_checkbox)
        self.background_hint = QLabel("Close this window to keep CampusNet in the system tray.")
        self.background_hint.setObjectName("mutedText")
        footer.addWidget(self.background_hint, 1)
        self.quit_button = QPushButton("Exit")
        self.quit_button.setObjectName("secondaryButton")
        self.quit_button.clicked.connect(self.quit_app)
        footer.addWidget(self.quit_button)
        outer.addLayout(footer)

        self.setStyleSheet("""
            QMainWindow, QWidget#page { background: #f4f7fb; color: #1d2939; font-family: 'Segoe UI', 'Inter', sans-serif; }
            QLabel { color: #1d2939; }
            QLabel#brandMark { background: transparent; border-radius: 14px; }
            QLabel#brandTitle { font-size: 24px; font-weight: 760; color: #101828; }
            QLabel#brandSubtitle { color: #667085; font-size: 12px; }
            QPushButton { padding: 9px 14px; border-radius: 8px; font-weight: 600; }
            QPushButton#primaryButton { background: #1d4ed8; color: white; border: 1px solid #1d4ed8; min-width: 145px; }
            QPushButton#primaryButton:hover { background: #1e40af; }
            QPushButton#primaryButton:disabled { background: #cbd5e1; border-color: #cbd5e1; color: #64748b; }
            QPushButton#secondaryButton { background: white; color: #344054; border: 1px solid #d0d5dd; }
            QPushButton#secondaryButton:hover { background: #f8fafc; border-color: #98a2b3; }
            QPushButton#linkButton { background: transparent; color: #1d4ed8; border: none; padding: 6px 4px; }
            QPushButton#linkButton:hover { background: #eff6ff; }
            QFrame#statusCard, QFrame#featureCard, QFrame#activityCard { background: white; border: 1px solid #e4e7ec; border-radius: 14px; }
            QLabel#statusIcon { background: #eff6ff; color: #1d4ed8; border-radius: 14px; font-size: 25px; font-weight: 700; }
            QLabel#statusBadge { background: #eff6ff; color: #1d4ed8; border-radius: 6px; padding: 4px 8px; font-size: 9px; font-weight: 800; letter-spacing: 1px; }
            QLabel#statusTitle { color: #101828; font-size: 19px; font-weight: 750; }
            QLabel#statusDetail { color: #667085; font-size: 12px; }
            QLabel#eyebrow { color: #667085; font-size: 10px; font-weight: 800; letter-spacing: 1.1px; }
            QLabel#featureSymbol { color: #2563eb; font-size: 23px; font-weight: 700; }
            QLabel#featureTitle { color: #101828; font-size: 13px; font-weight: 700; }
            QLabel#featureDetail { color: #667085; font-size: 11px; }
            QLabel#sectionTitle { color: #101828; font-size: 14px; font-weight: 750; }
            QLabel#mutedText { color: #667085; font-size: 11px; }
            QLabel#activityPreview { color: #475467; font-size: 12px; }
            QTextEdit#logView { background: #f8fafc; color: #344054; border: 1px solid #e4e7ec; border-radius: 8px; padding: 9px; font-family: Consolas, Menlo, monospace; font-size: 10px; }
            QCheckBox { spacing: 8px; color: #475467; font-size: 11px; }
            QCheckBox::indicator { width: 15px; height: 15px; }
        """)

        self._create_tray()
        QTimer.singleShot(250, self.start_monitoring)

    def _create_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        self.tray_toggle_action: QAction | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon(str(MARK_ICON_PATH)) if MARK_ICON_PATH.is_file() else self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("CampusNet · background authentication")
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        show_action = QAction("Open CampusNet", self)
        show_action.triggered.connect(self._show_from_tray)
        self.tray_toggle_action = QAction("Pause monitoring", self)
        self.tray_toggle_action.triggered.connect(self.toggle_monitoring)
        quit_action = QAction("Exit CampusNet", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(show_action)
        menu.addAction(self.tray_toggle_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _append_log(self, text: str) -> None:
        # Treat backend output as text; never let a message be interpreted as rich HTML.
        self.log_view.append(escape(text))
        self.activity_preview.setText(text)

    def _status_detail_for(self, text: str) -> str:
        details = {
            "Starting background monitor…": "Checking your campus internet connection.",
            "Signing in": "CampusNet found the college sign-in page and is submitting your saved credentials.",
            "Connected · monitoring session": "The Authentication Keepalive page is active in the background.",
            "Connected · session recovered": "Internet access has returned and session monitoring has resumed.",
            "Captive portal detected · connecting": "A fresh sign-in page was detected. CampusNet is attempting authentication.",
            "Checking connection · recovering if needed": "Checking internet access and looking for a fresh login redirect.",
            "Needs attention": "CampusNet couldn't complete authentication. Open the technical log for details.",
            "Internet available · monitoring": "Internet is reachable. CampusNet is watching for a new sign-in requirement.",
            "Monitoring stopped": "Monitoring is paused. CampusNet won't attempt automatic recovery until you start it again.",
            "Stopping monitor…": "Finishing the current network check before stopping.",
        }
        return details.get(text, "CampusNet is checking the connection and portal state.")

    def _set_status(self, text: str, kind: str) -> None:
        self._current_status_kind = kind
        styles = {
            "connected": ("ONLINE", "✓", "#ecfdf3", "#abefc6", "#067647", "#12b76a"),
            "working": ("WORKING", "↻", "#eff8ff", "#b2ddff", "#175cd3", "#2e90fa"),
            "error": ("ATTENTION", "!", "#fef3f2", "#fecdca", "#b42318", "#f04438"),
            "stopped": ("PAUSED", "Ⅱ", "#f2f4f7", "#d0d5dd", "#475467", "#98a2b3"),
        }
        badge, symbol, bg, border, foreground, accent = styles.get(kind, styles["working"])
        self.status_text.setText(text)
        self.status_detail.setText(self._status_detail_for(text))
        self.status_icon.setText(symbol)
        self.status_icon.setStyleSheet(
            f"background:{bg}; color:{accent}; border-radius:14px; font-size:25px; font-weight:700;"
        )
        self.status_badge.setText(badge)
        self.status_badge.setStyleSheet(
            f"background:{bg}; color:{foreground}; border:1px solid {border}; "
            "border-radius:6px; padding:4px 8px; font-size:9px; font-weight:800; letter-spacing:1px;"
        )
        if self.tray:
            self.tray.setToolTip(f"CampusNet · {text}")
        self._sync_monitoring_controls()

    def _sync_monitoring_controls(self) -> None:
        running = bool(self.worker and self.worker.isRunning())
        stopping = self.status_text.text() == "Stopping monitor…"
        self.toggle_monitoring_button.setEnabled(not stopping)
        self.toggle_monitoring_button.setText("Pause monitoring" if running else "Start monitoring")
        if self.tray_toggle_action:
            self.tray_toggle_action.setText("Pause monitoring" if running else "Start monitoring")

    def start_monitoring(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        try:
            self.config = load_config()
            load_credentials()
        except (FileNotFoundError, ValueError, CredentialError) as exc:
            _show_warning(self, "CampusNet setup required", str(exc))
            saved = self.edit_settings()
            # Setup used to run before the window existed, and monitoring then
            # started on its own. Retry once after a successful save so finishing
            # setup still leaves CampusNet monitoring, as it did before.
            if saved and not self._setup_retry_done:
                self._setup_retry_done = True
                self.start_monitoring()
            return
        self.worker = BackendWorker(self.config, self)
        self.worker.log_line.connect(self._append_log)
        self.worker.state_changed.connect(self._set_status)
        self.worker.failed.connect(self._on_worker_failed)
        self.worker.stopped.connect(self._on_worker_stopped)
        self.worker.finished.connect(self._sync_monitoring_controls)
        self.worker.start()
        self._set_status("Starting background monitor…", "working")
        self._append_log("Desktop app started. Credentials are retrieved from the OS credential store.")
        self._sync_monitoring_controls()

    def toggle_monitoring(self) -> None:
        if self.worker and self.worker.isRunning():
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def stop_monitoring(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self._set_status("Stopping monitor…", "working")
        else:
            self._set_status("Monitoring stopped", "stopped")
        self._sync_monitoring_controls()

    def _on_worker_stopped(self) -> None:
        if self.status_text.text() != "Needs attention":
            self._set_status("Monitoring stopped", "stopped")
        self._sync_monitoring_controls()

    def _on_worker_failed(self, message: str) -> None:
        self._append_log(f"ERROR  {message}")
        self._set_status("Needs attention", "error")
        _show_warning(self, "CampusNet needs attention", message)

    def edit_settings(self) -> bool:
        """Show the setup dialog. Returns True when new settings were saved."""
        try:
            config = load_config()
        except (FileNotFoundError, ValueError):
            config = None
        dialog = SetupDialog(config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved_config:
            self.config = dialog.saved_config
            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(is_enabled())
            self.startup_checkbox.blockSignals(False)
            self._append_log("Settings saved securely.")
            if self.worker and self.worker.isRunning():
                _show_information(
                    self,
                    "Settings saved",
                    "Your settings have been saved. Pause and start monitoring to apply changes to the current session.",
                )
            return True
        return False

    def _change_autostart(self, enabled: bool) -> None:
        previous = self.config
        try:
            set_enabled(enabled)
            updated = replace(previous, launch_at_startup=enabled)
            write_config(updated)
            self.config = updated
        except Exception as exc:
            # Roll back the OS startup entry and restore the visible state if
            # persistence fails, so a checked box always matches the actual setting.
            try:
                set_enabled(previous.launch_at_startup)
            except Exception:
                pass
            _show_warning(self, "Startup setting failed", str(exc))
            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(previous.launch_at_startup)
            self.startup_checkbox.blockSignals(False)
            return
        label = "Launch at startup enabled." if enabled else "Launch at startup disabled."
        self._append_log(label)

    def toggle_activity_details(self) -> None:
        visible = not self.log_view.isVisible()
        self.log_view.setVisible(visible)
        self.details_button.setText("Hide technical log" if visible else "View technical log")

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_from_tray()

    def quit_app(self) -> None:
        self._allow_close = True
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            if not self.worker.wait(15000):
                _show_warning(
                    self,
                    "Still stopping",
                    "CampusNet is waiting for the current network request to finish. Try exiting again in a few seconds.",
                )
                self._allow_close = False
                return
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming convention
        if self._allow_close:
            event.accept()
            return
        if self.tray is not None:
            self.hide()
            if not self._tray_notice_shown:
                self.tray.showMessage(
                    "CampusNet is still running",
                    "The window is hidden. CampusNet will keep monitoring in the background. "
                    "Use the tray icon to reopen it or choose Exit to stop it.",
                    QSystemTrayIcon.MessageIcon.Information,
                    4500,
                )
                self._tray_notice_shown = True
            event.ignore()
            return
        choice = _show_message(
            self,
            QMessageBox.Icon.Question,
            "Exit CampusNet?",
            "No system tray is available. Exit CampusNet and stop background monitoring?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice == QMessageBox.StandardButton.Yes:
            self.quit_app()
        event.ignore()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("CampusNet")
    app.setWindowIcon(_campusnet_icon())
    app.setQuitOnLastWindowClosed(False)

    already_running, instance_server = _claim_single_instance()
    if already_running:
        # The live instance has been asked to bring its window to the front.
        return

    # Only the config file is read before the window appears. The credential
    # store is not touched here: MainWindow.start_monitoring already validates
    # credentials just after the window is shown, and reads them for real on the
    # worker thread. Probing the OS credential store here duplicated that work
    # and its result was discarded.
    try:
        config = load_config()
    except (FileNotFoundError, ValueError):
        dialog = SetupDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.saved_config:
            return
        config = dialog.saved_config

    window = MainWindow(config)
    window.show()

    if instance_server is not None:
        def show_for_other_instance() -> None:
            connection = instance_server.nextPendingConnection()
            if connection is not None:
                connection.disconnectFromServer()
                connection.deleteLater()
            window._show_from_tray()

        instance_server.newConnection.connect(show_for_other_instance)
        # Keep both alive for as long as the window lives.
        window._instance_server = instance_server
        window._instance_handler = show_for_other_instance

    # Reconciled after the window is on screen. Older config files have no
    # launch_at_startup key and default to True, so the OS login item is
    # synchronized to match the checked UI and the persisted setting.
    try:
        if is_enabled() != config.launch_at_startup:
            set_enabled(config.launch_at_startup)
    except Exception as exc:
        _show_warning(window, "Startup setting failed", str(exc))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
