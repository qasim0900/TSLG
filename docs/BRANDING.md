# Techset LeadGen Brand Reference

This file records the brand evidence and implementation decisions used by Techset LeadGen. It separates values observed on the official Techset Solutions website from tones derived locally for accessibility.

Research and asset verification date: **2026-10-20**.

## 1. Source of truth

The primary reference is the [Techset Solutions official website](https://techsetsolutions.com/). The application uses these official public assets:

- [Techset monogram logo](https://techsetsolutions.com/images/logo/techset-logo.png)
- [Techset logo with text](https://techsetsolutions.com/images/logo/techset-logo_with_text.png)
- [Techset favicon](https://techsetsolutions.com/favicon.ico)

The official site's public styles establish a green-and-gold palette, dark ink surfaces, light warm canvas, rounded/pill controls, and Inter typography. The local values below were recorded from those styles and assets rather than estimated from memory.

No official SVG or separate dark-mode logo variant was found during the research. The application therefore uses the same unmodified transparent PNG on light and dark surfaces, with a quiet neutral/green-tinted container behind it when contrast is helpful.

## 2. Product identity

| Item | Canonical value | Code owner |
|---|---|---|
| Product name | **Techset LeadGen** | `branding.PRODUCT_NAME` |
| Parent brand | **Techset Solutions** | `branding.PARENT_BRAND` |
| Product tagline | **Sales and lead intelligence** | `branding.PRODUCT_TAGLINE` |
| Website | `https://techsetsolutions.com/` | `branding.OFFICIAL_WEBSITE` |
| UI typeface | Inter | `branding.FONT_FAMILY`, `branding.FONT_ASSET` |

The header keeps the official Techset Solutions artwork intact and renders **Techset LeadGen** as adjacent application text. The product name is not baked into, overlaid on, or used to modify the official logo file.

Capitalization must remain exactly `Techset LeadGen` in visible product copy, window titles, and report titles.

## 3. Verified official values

These tokens are direct observations from the official website or logo asset. The desktop UI defines the ones it uses centrally in `desktop_ui/theme.py`.

| Token | Value | Observed role | Local use |
|---|---:|---|---|
| `BRAND_PRIMARY` | `#39B54A` | Primary green | Selected tabs, dark-theme accent, charts, decorative emphasis |
| `BRAND_LOGO_GREEN` | `#5AB949` | Dominant green in official logo artwork | Provenance/reference; the logo bitmap itself is displayed unchanged |
| `BRAND_PRIMARY_HOVER` | `#32CD32` | Bright green hover/accent | Dark-theme interactive hover treatment |
| `BRAND_SECONDARY` | `#FFCB4A` | Gold secondary accent | Comparison actions and secondary emphasis |
| `BRAND_INK` | `#0A1414` | Dark foreground/background | Dark canvas, export actions, text on bright brand colors |
| `BRAND_CANVAS` | `#FBFAF8` | Warm light background | Light-theme surface |
| `BRAND_MUTED` | `#757693` | Muted website copy | Brand reference; larger/decorative copy where contrast permits |
| `BRAND_MUTED_DARK` | `#999AA1` | Muted copy on dark surfaces | Dark-theme secondary text |
| `BRAND_SURFACE_LIGHT` | `#F5F5F5` | Light card/background | Light container surfaces |
| `BRAND_BORDER_LIGHT` | `#C3C6CE` | Light borders/dividers | Light outline variants |
| `BRAND_SURFACE_DARK` | `#0A1D3B` | Dark elevated surface | Dark high-emphasis containers |

Import these colors from `desktop_ui/theme.py`; new controls should not duplicate the hex values.

**Re-verification, 2026-10-20 (Qt audit).** The official site's compiled stylesheets (`/_next/static/css/*.css`) were downloaded and searched. `#39B54A`, `#FFCB4A`, `#0A1414`, `#FBFAF8`, `#0A1D3B` (as `bg-[#0a1d3b]`), `#C3C6CE`, `#F5F5F5`, and `#32CD32` are present, and the font stack is Inter. `#5AB949` comes from the logo artwork rather than CSS; `#757693` and `#999AA1` were not found as hex literals and may be expressed in another notation.

## 4. Derived accessibility values

The official visual palette is the identity reference, but every official color is not suitable for every foreground/background pairing. The following values are application derivatives and must not be described as values taken from the website.

| Token | Value | Reason |
|---|---:|---|
| `BRAND_PRIMARY_ACCESSIBLE` | `#287D35` | Darker green for light-theme filled actions and green text |
| `BRAND_PRIMARY_ACTION_HOVER` | `#1F642A` | Hover state paired with the accessible green |
| `BRAND_MUTED_ACCESSIBLE` | `#62637A` | Secondary text on the warm light canvas |
| Comparison hover | `#E2A900` | Darker interaction state for the gold button |
| Tertiary UI colors | Theme-specific teal/neutral values | Separates semantic and utility actions from the parent-brand accent |

Measured WCAG contrast ratios:

| Pair | Ratio | Application decision |
|---|---:|---|
| White on official green `#39B54A` | 2.66:1 | Do not use for normal-size button labels |
| Ink `#0A1414` on official green `#39B54A` | 7.02:1 | Suitable for dark-theme green buttons and badges |
| White on derived green `#287D35` | 5.15:1 | Suitable for normal text in light-theme filled actions |
| Ink `#0A1414` on gold `#FFCB4A` | 12.37:1 | Suitable for comparison actions |
| Official muted `#757693` on canvas `#FBFAF8` | 4.22:1 | Below the 4.5:1 normal-text target |
| Derived muted `#62637A` on canvas `#FBFAF8` | 5.62:1 | Used for normal-size light-theme secondary text |

Success, warning, error, disabled, surface, and outline states use the semantic tokens in `desktop_ui/theme.py` (for example `#BA1A1A` errors on light surfaces and `#FFB4AB` on dark surfaces, where `#BA1A1A` measures about 2.5:1). Brand green does not replace every semantic state.

## 5. Typography

The official site uses Inter with a broad variable-weight range. The repository bundles the Google Fonts variable file locally so the desktop UI does not depend on network font loading.

Observed website direction:

- body copy around 16 px, 26 px line height, weight 400;
- headings at weight 700 or 800; and
- concise semibold labels and pill-button text.

Application adaptation in the Qt stylesheet (`desktop_ui/theme.py`):

| Role | Size | Weight |
|---|---:|---:|
| Page title | 28 px | 700 |
| KPI value | 25 px | 700 |
| Dialog title | 22 px | 700 |
| Product name (sidebar) | 18 px | 700 |
| Summary value | 18 px | 700 |
| Section title | 17 px | 650 |
| Base text | 10 pt application font | 400 |
| Field labels, buttons | base size | 600 |
| Tagline | 12 px | 400 |

`ThemeManager.apply()` registers the bundled font with `QFontDatabase.addApplicationFont(assets/fonts/Inter-Variable.ttf)` and sets it as the application font, so no network font loading is involved.

## 6. Shape, spacing, and interaction language

The official site favors open spacing, rounded surfaces, and pill-shaped calls to action. The Qt stylesheet adapts that language:

| Element | Treatment |
|---|---|
| Buttons | 36 px minimum height, 18 px radius (pill), semibold label; filled green primary, neutral secondary, gold tertiary, red destructive |
| Inputs, combos, date fields | 36 px minimum height, 8 px radius, chevron drop-down indicator, muted fill when disabled |
| Cards and group boxes | 14 px radius, 1 px border; KPI cards add a 3 px accent top border (green, gold, red, or neutral) |
| Tables | 10 px radius frame, alternating rows, painted row-action buttons sized to the row |
| Tabs | 3 px official-green indicator on the selected tab |
| Focus | 2 px ring: green `#287D35` (light) or gold `#FFCB4A` (dark) on outlined controls; gold, ink, or white on filled buttons. Every focus state differs from the unfocused edge by at least 3:1 |

Motion is limited to Qt's native interaction feedback; there is no decorative animation.

## 7. Asset inventory and provenance

SHA-256 values allow a maintainer to confirm that a local file still matches the researched asset.

| Local asset | Source | Format / dimensions | SHA-256 | Purpose |
|---|---|---|---|---|
| `assets/techset_logo.png` | Official monogram URL above | PNG, 250×250, RGBA | `cd06bda20eec2e1f97afca1769e080947f3be0a2d3fe7b50b091dbde97a443fc` | Header logo |
| `assets/techset_logo_with_text.png` | Official logo-with-text URL above | PNG, 250×250, RGBA | `ac431cdabc21359d3fa063ca25be266c89900ce3ff965bf3c23bcb4913741e4e` | Available official lockup |
| `assets/techset_favicon.ico` | Official favicon URL above | ICO, six embedded sizes up to 256×256 | `0aaa3ac2af05a0d48a033e26156e258f397f4b87549899d6a5fc44a0cb5a4b4f` | Desktop window icon |
| `assets/favicon.ico` | Copy of official favicon | ICO | `0aaa3ac2af05a0d48a033e26156e258f397f4b87549899d6a5fc44a0cb5a4b4f` | Conventional packaging alias |
| `assets/icon.png` | Copy of official monogram | PNG, 250×250, RGBA | `cd06bda20eec2e1f97afca1769e080947f3be0a2d3fe7b50b091dbde97a443fc` | Conventional packaging icon |
| `assets/fonts/Inter-Variable.ttf` | [Google Fonts Inter repository](https://github.com/google/fonts/tree/main/ofl/inter) | Variable TrueType | `29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031` | Local UI font |
| `assets/fonts/OFL.txt` | Google Fonts Inter repository | SIL Open Font License text | `5b9321a4298cfeb6b34354164a1c3afc3db114569984c502b9b35d988fd58c57` | Font license |

The older `fdt_logo*` files have been removed from the working tree. `assets/icons/chevron_down_{light,dark,disabled}.svg` are application-drawn drop-down indicators, not brand assets.

## 8. Correct logo usage

- Use `branding.LOGO_ASSET` for the monogram and `branding.LOGO_WITH_TEXT_ASSET` when the full official lockup is specifically required.
- Resolve files with `desktop_ui.theme.asset_path()`, which works from source and from an installed wheel.
- Preserve aspect ratio; the sidebar renders the monogram at 36 px inside a 40 px box.
- Keep transparent padding and do not crop the mark.
- Do not recolor, rotate, distort, redraw, add product text inside, or apply filters to the logo artwork.
- Use the same official asset in both themes until the brand owner publishes a separate dark variant.
- Place the logo on a surface that preserves edge contrast rather than modifying the bitmap.
- Keep the accessible name **Techset Solutions logo** on the logo label.

The window icon uses `branding.FAVICON_ASSET` through `QIcon(asset_path(...))`.

## 9. Wordmark and responsive header

The sidebar header consists of three independent pieces:

1. the official monogram image;
2. the product name **Techset LeadGen** in the foreground color; and
3. the tagline in secondary text.

The window opens at 1360 × 860 px with a 760 × 600 px minimum. Below 980 px the sidebar collapses to the monogram and icon-only navigation with tooltips, so the name is hidden rather than truncated.

## 10. Light and dark themes

Both themes are a `QPalette` plus one global stylesheet built from the same tokens.

### Light

- canvas: `#FBFAF8`;
- primary action: derived accessible green `#287D35` with white content;
- selected/decorative accent: official green `#39B54A`;
- text: ink `#0A1414`;
- normal secondary text: accessible muted `#62637A`; and
- surfaces: white and `#F5F5F5` (also disabled inputs), with `#ECEFEB` for table headers and disabled buttons.

### Dark

- canvas: ink `#0A1414`, with `#122321` cards and a `#081311` sidebar;
- official dark surface `#0A1D3B` for table headers and disabled buttons;
- primary action: official green `#39B54A` with ink content;
- secondary accent: gold `#FFCB4A` with ink content;
- text `#F2F5F2` and secondary text `#B7BDBA`.

The toggle in the top bar calls `ThemeManager.toggle()`, which re-applies the palette and stylesheet and saves the choice in `QSettings`; the shell recolors its navigation icons from the `theme_changed` signal. There is no second theme provider or parallel token system.

## 11. Reports

`reports/html_template.py` carries the same palette and Inter-first font stack into exported HTML. Reports do not require an internet connection to display content, although the browser falls back to an installed system sans-serif because the TTF is not embedded in each HTML file.

Report requirements:

- page title and visible brand line use **Techset LeadGen**;
- primary accents use brand green and gold with accessible foregrounds;
- Matplotlib chart palettes start with green and use gold/semantic colors for distinction;
- sensitive client values remain obscured until mouse hover or keyboard focus; and
- report content stays readable when printed.

## 12. Implementation ownership

| Concern | Source of truth |
|---|---|
| Product strings and asset names | `branding.py` |
| UI color tokens, palette, stylesheet, theme persistence | `desktop_ui/theme.py` |
| Navigation icons | `desktop_ui/icons.py` |
| Shell logo, name, and tagline | `desktop_ui/main_window.py` |
| In-app chart colors | `desktop_ui/pages/sales_page.py` |
| Window icon, font registration | `desktop_ui/main_window.py`, `desktop_ui/theme.py` |
| Report CSS | `reports/html_template.py` |
| Report chart colors | `reports/charts_generator.py` |

When changing a value, update its owning source rather than patching individual screens.

## 13. Maintenance checklist

When the official brand site changes:

1. Reinspect the live site and public asset files.
2. Record the verification date and direct official source URL.
3. Download the original file without resizing or recompressing it.
4. Check file type, dimensions, transparency, and SHA-256.
5. Distinguish verified values from application-derived accessible values.
6. Update the central constant or asset reference.
7. Check light and dark modes at narrow and desktop widths.
8. Verify the window icon, the logo's accessible name, and `asset_path()` resolution from an installed wheel.
9. Generate all three report types and inspect screen and print contrast.
10. Run the repository's lint, type, security, and test commands.

Useful local integrity command:

```bash
sha256sum \
  assets/techset_logo.png \
  assets/techset_logo_with_text.png \
  assets/techset_favicon.ico \
  assets/fonts/Inter-Variable.ttf \
  assets/fonts/OFL.txt
```

## 14. Rights and licensing

The files downloaded from the Techset Solutions site remain brand assets owned or controlled by their respective rights holder. Their presence in the application does not grant broader trademark rights. Confirm deployment and distribution rights with the brand owner.

Inter is distributed under the SIL Open Font License included at `assets/fonts/OFL.txt`. The repository currently does not contain a root license covering the application source code.
