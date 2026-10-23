# PyInstaller build of the Techset LeadGen desktop application (one folder, windowed).
#
#   Windows:  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#   Any OS:   poetry run pyinstaller packaging/TechsetLeadGen.spec --noconfirm
#
# PyInstaller builds for the operating system it runs on: build the Windows
# executable on Windows. Output: dist/TechsetLeadGen/TechsetLeadGen(.exe).
# The data folder (data/sales.db, backups) is created next to the executable
# unless FDT_DATA_DIR points elsewhere, so install it in a folder the user can write to.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - provided by PyInstaller

datas = [
    (str(ROOT / "assets"), "assets"),
    # Alembic loads the migration scripts from files at run time.
    (str(ROOT / "crm" / "alembic.ini"), "crm"),
    (str(ROOT / "crm" / "migrations"), "crm/migrations"),
    # The password policy's local list of common passwords (read from a file, not imported).
    (str(ROOT / "crm" / "security" / "common-passwords.txt.gz"), "crm/security"),
]
# Windows has no system time-zone database; zoneinfo reads it from the tzdata package.
datas += collect_data_files("tzdata")

hiddenimports = [
    # Imported by the migration scripts, which are data files (not the bundled test suite).
    *collect_submodules("alembic", filter=lambda name: not name.startswith("alembic.testing")),
    "sqlalchemy.dialects.sqlite",
    "argon2",
    "_cffi_backend",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "mypy", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TechsetLeadGen",
    icon=str(ROOT / "assets" / "techset_favicon.ico"),
    console=False,  # a desktop window, no terminal
    disable_windowed_traceback=False,
    version=None,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TechsetLeadGen",
)
