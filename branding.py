"""Canonical product identity and local asset names for Techset LeadGen.

Visual color tokens live in :mod:`desktop_ui.theme`; this module keeps product
copy and asset paths consistent across the desktop shell and exported reports.
Asset paths are relative to the ``assets`` directory unless noted.
"""

PRODUCT_NAME = "Techset LeadGen"
PRODUCT_VERSION = "0.2.0"
PARENT_BRAND = "Techset Solutions"
PRODUCT_TAGLINE = "Sales and lead intelligence"
OFFICIAL_WEBSITE = "https://techsetsolutions.com/"

# The wordmark shows PRODUCT_NAME in two weights: "Techset" bold, "LeadGen" in brand green.
WORDMARK_PARTS = ("Techset", "LeadGen")

LOGO_ASSET = "techset_logo.png"
LOGO_WITH_TEXT_ASSET = "techset_logo_with_text.png"
FAVICON_ASSET = "techset_favicon.ico"
FONT_FAMILY = "Plus Jakarta Sans"
# Static weights instanced from the Google Fonts variable files: Qt picks a weight
# per file but does not drive a variable font's weight axis.
FONT_ASSETS = tuple(f"fonts/PlusJakartaSans-{style}.ttf"
                    for style in ("Regular", "Medium", "SemiBold", "Bold", "ExtraBold"))
FONT_ASSET = FONT_ASSETS[0]
MONO_FONT_FAMILY = "JetBrains Mono"
MONO_FONT_ASSETS = ("fonts/JetBrainsMono-Regular.ttf", "fonts/JetBrainsMono-Bold.ttf")
MONO_FONT_ASSET = MONO_FONT_ASSETS[0]


__all__ = [
    "PRODUCT_NAME",
    "PRODUCT_VERSION",
    "PARENT_BRAND",
    "PRODUCT_TAGLINE",
    "OFFICIAL_WEBSITE",
    "WORDMARK_PARTS",
    "LOGO_ASSET",
    "LOGO_WITH_TEXT_ASSET",
    "FAVICON_ASSET",
    "FONT_FAMILY",
    "FONT_ASSET",
    "FONT_ASSETS",
    "MONO_FONT_FAMILY",
    "MONO_FONT_ASSET",
    "MONO_FONT_ASSETS",
]
