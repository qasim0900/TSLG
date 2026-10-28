# PyInstaller build of the Techset LeadGen desktop application (one folder, windowed).
#
#   Windows:  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#   Any OS:   poetry run pyinstaller packaging/TechsetLeadGen.spec --noconfirm
#
# PyInstaller builds for the operating system it runs on: build the Windows
# executable on Windows. Output: dist/TechsetLeadGen/TechsetLeadGen(.exe).
# Runtime data is kept outside the bundle; FDT_DATA_DIR can point at the
# user-writable application-data folder selected for a deployment.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - provided by PyInstaller
PACKAGE = ROOT / "src" / "techset_leadgen"

datas = [
    (str(PACKAGE / "assets"), "techset_leadgen/assets"),
    # Alembic loads the migration scripts from files at run time.
    (str(PACKAGE / "database" / "alembic.ini"), "techset_leadgen/database"),
    (str(PACKAGE / "database" / "migrations"), "techset_leadgen/database/migrations"),
    # The password policy's local list of common passwords (read from a file, not imported).
    (str(PACKAGE / "security" / "common-passwords.txt.gz"), "techset_leadgen/security"),
]
# Windows has no system time-zone database; zoneinfo reads it from the tzdata package.
datas += collect_data_files("tzdata")

hiddenimports = [
    # Imported by the migration scripts, which are data files (not the bundled test suite).
    *collect_submodules("alembic", filter=lambda name: not name.startswith("alembic.testing")),
    "sqlalchemy.dialects.sqlite",
    # The shared team database (TSLG_DATABASE_URL=postgresql+psycopg://...).
    "sqlalchemy.dialects.postgresql",
    "psycopg",
    "argon2",
    "_cffi_backend",
]

a = Analysis(  # noqa: F821
    [str(PACKAGE / "__main__.py")],
    pathex=[str(ROOT / "src")],
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
    icon=str(PACKAGE / "assets" / "techset_favicon.ico"),
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
