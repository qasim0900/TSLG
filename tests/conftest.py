import os
import shutil
import sys
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="fdt-tests-")
os.environ["FDT_DATA_DIR"] = os.path.join(_SANDBOX, "data")
os.environ["FDT_LOG_DIR"] = os.path.join(_SANDBOX, "logs")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_SANDBOX, "config")
# Animations finish instantly in tests, so results never depend on timing.
os.environ["TSLG_REDUCED_MOTION"] = "1"


def _delete_leftover_windows() -> None:
    """Delete the windows tests left open while the application still exists.

    Left for interpreter shutdown, PySide deletes them after the application object, and one
    of them crashed the process (segmentation fault) after every test had passed (QA BUG-108).
    """
    widgets = sys.modules.get("PySide6.QtWidgets")
    application = widgets.QApplication.instance() if widgets is not None else None
    if application is None:
        return
    from PySide6.QtCore import QCoreApplication, QEvent

    for window in application.topLevelWidgets():
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def pytest_sessionfinish(session, exitstatus):
    _delete_leftover_windows()
    shutil.rmtree(_SANDBOX, ignore_errors=True)
