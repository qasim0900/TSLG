PRODUCT_NAME = "Techset LeadGen"
PRODUCT_VERSION = "0.2.0"
PARENT_BRAND = "Techset Solutions"
PRODUCT_TAGLINE = "Outreach & team workflow"
OFFICIAL_WEBSITE = "https://techsetsolutions.com/"

WORDMARK_PARTS = ("Techset", "LeadGen")

LOGO_ASSET = "techset_logo.png"
LOGO_WITH_TEXT_ASSET = "techset_logo_with_text.png"
FAVICON_ASSET = "techset_favicon.ico"
FONT_FAMILY = "Plus Jakarta Sans"
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

