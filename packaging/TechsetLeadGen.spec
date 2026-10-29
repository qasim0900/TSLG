from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
PACKAGE = ROOT / "src" / "techset_leadgen"

datas = [
    (str(PACKAGE / "assets"), "techset_leadgen/assets"),
    (str(PACKAGE / "database" / "alembic.ini"), "techset_leadgen/database"),
    (str(PACKAGE / "database" / "migrations"), "techset_leadgen/database/migrations"),
    (str(PACKAGE / "security" / "common-passwords.txt.gz"), "techset_leadgen/security"),
]
datas += collect_data_files("tzdata")

hiddenimports = [
    *collect_submodules("alembic", filter=lambda name: not name.startswith("alembic.testing")),
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.postgresql",
    "psycopg",
    "argon2",
    "_cffi_backend",
]

a = Analysis(
    [str(PACKAGE / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "mypy", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TechsetLeadGen",
    icon=str(PACKAGE / "assets" / "techset_favicon.ico"),
    console=False,
    disable_windowed_traceback=False,
    version=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TechsetLeadGen",
)

