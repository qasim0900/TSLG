import os
import shutil
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="fdt-tests-")
os.environ["FDT_DATA_DIR"] = os.path.join(_SANDBOX, "data")
os.environ["FDT_LOG_DIR"] = os.path.join(_SANDBOX, "logs")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_SANDBOX, "config")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_SANDBOX, ignore_errors=True)
