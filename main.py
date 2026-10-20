"""Punto de entrada de Techset LeadGen.

Inicializa la base de datos, configura la página Flet (tema, icono, dimensiones)
y lanza la aplicación principal. Ejecutar con: python main.py
"""

import logging
import os
from logging.handlers import RotatingFileHandler

import flet as ft
from branding import FAVICON_ASSET, FONT_ASSET, FONT_FAMILY, PRODUCT_NAME
from ui.user_ui import FDTApp
from theme import build_light_theme, build_dark_theme
from core.db import init_db, get_base_path, get_logs_dir
from utils.flet_perf import install_cheap_control_repr

logger = logging.getLogger("fdt.app")

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_fdt_handler", False) for handler in root.handlers):
        return

    level = getattr(logging, os.environ.get("FDT_LOG_LEVEL", "INFO").upper(), logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(formatter)
    console._fdt_handler = True
    root.addHandler(console)

    try:
        file_handler = RotatingFileHandler(
            get_logs_dir() / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    except OSError:
        logger.warning("Could not create the application log", exc_info=True)
    else:
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler._fdt_handler = True
        root.addHandler(file_handler)

    root.setLevel(level)


def _show_startup_error(page: ft.Page, error: Exception) -> None:
    page.controls.clear()
    page.add(
        ft.Column(
            [
                ft.Icon(ft.Icons.ERROR_OUTLINE, color=ft.Colors.ERROR, size=48),
                ft.Text("The application could not start", size=20, weight=ft.FontWeight.BOLD),
                ft.Text(str(error), selectable=True),
                ft.Text(
                    f"Technical details: {get_logs_dir() / 'app.log'}",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    selectable=True,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
    )


def main(page: ft.Page):
    page.window.visible = False
    install_cheap_control_repr()
    try:
        init_db()

        page.title = PRODUCT_NAME
        page.window.height = 720
        page.window.min_height = 600
        page.window.min_width = 360

        # Ruta a assets (compatible con .exe compilado)
        base_path = get_base_path()
        icon_path = base_path / "assets" / FAVICON_ASSET

        if icon_path.exists():
            page.window.icon = str(icon_path)

        # Inter is the typeface used by the official Techset Solutions site.
        # The font is bundled locally so desktop and packaged builds do not
        # depend on a network request.
        page.fonts = {FONT_FAMILY: FONT_ASSET}

        # Configurar temas (patrón oficial de Flet)
        page.theme = build_light_theme()
        page.dark_theme = build_dark_theme()
        page.theme_mode = ft.ThemeMode.LIGHT
        page.bgcolor = None

        app = FDTApp(page)
        page.add(app)
        logger.info("Application started")
    except Exception as e:
        logger.exception("Fatal error while starting the application")
        _show_startup_error(page, e)
    finally:
        page.window.visible = True


if __name__ == "__main__":
    configure_logging()
    try:
        ft.run(main)
    except (ConnectionResetError, BrokenPipeError, OSError):
        # Errores de cleanup asyncio en Windows al cerrar — ignorar
        logger.debug("Ignored shutdown error", exc_info=True)
