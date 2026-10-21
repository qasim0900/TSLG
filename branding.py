"""Canonical product identity and local asset names for Techset LeadGen.

Visual color tokens live in :mod:`theme.colors`; this module keeps product
copy and asset paths consistent across the desktop shell and exported reports.
Asset paths are relative to the ``assets`` directory unless noted.
"""

PRODUCT_NAME = "Techset LeadGen"
PRODUCT_VERSION = "0.2.0"
PARENT_BRAND = "Techset Solutions"
PRODUCT_TAGLINE = "Sales and lead intelligence"
OFFICIAL_WEBSITE = "https://techsetsolutions.com/"

LOGO_ASSET = "techset_logo.png"
LOGO_WITH_TEXT_ASSET = "techset_logo_with_text.png"
FAVICON_ASSET = "techset_favicon.ico"
FONT_FAMILY = "Inter"
FONT_ASSET = "fonts/Inter-Variable.ttf"


__all__ = [
    "PRODUCT_NAME",
    "PRODUCT_VERSION",
    "PARENT_BRAND",
    "PRODUCT_TAGLINE",
    "OFFICIAL_WEBSITE",
    "LOGO_ASSET",
    "LOGO_WITH_TEXT_ASSET",
    "FAVICON_ASSET",
    "FONT_FAMILY",
    "FONT_ASSET",
]
