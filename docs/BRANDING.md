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
| UI typeface | Plus Jakarta Sans (JetBrains Mono for IDs, times and paths) | `branding.FONT_FAMILY`, `branding.FONT_ASSETS`, `branding.MONO_FONT_ASSETS` |

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

The official site uses Inter. The 2026-10 application redesign (the "Techset LeadGen — App redesign" canvas) sets the desktop UI in **Plus Jakarta Sans**, with **JetBrains Mono** for record IDs, audit timestamps, one-time codes, and file paths. Both come from the Google Fonts repository and are bundled, so the UI never loads fonts from the network. Exported HTML reports keep their Inter-first stack (section 11).

Qt selects a weight per font file but does not drive a variable font's weight axis (every weight between 400 and 700 rendered as Regular). The bundled files are therefore static instances of the official variable fonts, cut at 400, 500, 600, 700, and 800 (JetBrains Mono at 400 and 700) with `fontTools.varLib.instancer`; the family name is unchanged, which the fonts' OFL permits because they declare no Reserved Font Name.

Application type scale (`desktop_ui/theme.py`):

| Role | Size | Weight |
|---|---:|---:|
| Page title | 24 px | 800 |
| KPI value | 28 px | 800 |
| Metric-grid value | 22 px | 800 |
| Sign-in heading | 26 px | 800 |
| Dialog title | 19 px | 800 |
| Detail-panel title | 18 px | 800 |
| Top-bar page title | 16 px | 800 |
| Section (card) title | 15 px | 700 |
| Wordmark "Techset" / "LeadGen" | 17 px | 800 / 500 |
| Base text | 14 px application font | 400 |
| Table text | 13 px | 400 |
| Buttons, inputs | 13 px | 600 / 400 |
| Field labels, table headers | 12 px | 600 / 700 |
| Navigation group headers, tagline | 11 px / 9 px uppercase | 700 |

`ThemeManager.apply()` registers every bundled weight with `QFontDatabase.addApplicationFont()` and sets Plus Jakarta Sans as the application font. In-app charts are drawn natively with the same fonts and theme tokens; only exported reports use Matplotlib.

## 6. Shape, spacing, and interaction language

| Element | Treatment |
|---|---|
| Buttons | every bordered button is 40 px tall (`BUTTON_HEIGHT` in `desktop_ui/theme.py`, borders included), on every page, in every dialog and in table rows; icon-only buttons and pager buttons are 40 × 40; 10 px radius, semibold label, optional 16 px line icon; filled green primary, outlined secondary, transparent ghost, red-outlined danger, filled red for confirmed destructive actions. Only borderless glyphs (a dialog's close cross, the eye in password fields, table row icons) use a 32 px hit area |
| Inputs, combos, date fields | 40 px tall, 10 px radius, search fields with a leading icon, calendar icon on date fields |
| Cards | 14 px radius, 1 px hairline border; card headers (title, subtitle, actions) separated by a hairline |
| KPI cards | label and a 34 px tinted icon chip (green or gold) on top, 28 px value, short note |
| Tables | 42 px header on the soft surface, 52 px rows separated by hairlines, row hover tint, tinted selection; badges with a leading dot, initials avatars, monospace IDs, icon-only row actions |
| Tabs | 3 px brand-green underline on the selected tab |
| Sidebar | 252 px (76 px collapsed): grouped navigation (Overview, Pipeline, Admin) with counts, a brand-green marker beside the current page, local-database card, collapse control |
| Feedback | toasts at the bottom centre for confirmations; inline alerts (info, warning, error) in forms; errors still open a dialog |
| Focus | 2 px ring in `#287D35` (light) or `#74C763` (dark) on outlined controls; gold or ink on filled buttons. Every focus state differs from the unfocused edge by at least 3:1 |

### Motion

The redesign's motion layer animates only position, scale, and opacity, never layout or meaning (`desktop_ui/motion.py`, with the redesign's curves: ease `cubic-bezier(.22,.61,.36,1)`, ease-out `(.2,.8,.2,1)`, spring `(.34,1.56,.64,1)`):

| Where | Motion |
|---|---|
| After sign-in | the sidebar slides in, the top bar drops in, navigation entries follow 50 ms apart |
| Every page | sections (and each KPI card) rise 14 px into place, 60 ms apart; table rows fade and slide in; charts grow from the axis (bars, 0.8 s) or sweep in from the left (bar lists and the funnel, 1 s) |
| Hover and press | buttons lift 1 px and dip to 96% when pressed; KPI cards lift 3 px with a shadow while their icon chip scales and tilts; navigation icons and avatars grow slightly (spring) |
| Navigation and tabs | the green current-page marker grows in (spring); the tab underline grows out from the tab's centre |
| Controls | switches spring across; the sidebar width glides when collapsed or expanded; the theme cross-fades instead of snapping |
| Feedback | toasts spring up and fade out; dialogs rise in over a backdrop that fades in; menus drop down; alerts fade in |

Motion is off when the operating system asks for less of it (Windows "Animation effects"), when the user turns on **Settings → Your account → Reduce motion**, or when `TSLG_REDUCED_MOTION=1` is set (the test suite sets it); everything then appears in its final state, as the design's `prefers-reduced-motion` rule does.

### Dialogs and pop-ups

Application dialogs subclass `ModalDialog` (`desktop_ui/modal.py`) and open as a card centred *inside* the window over a dimmed backdrop, not as separate windows: on Wayland the compositor places top-level windows (GNOME opened them in the top-left corner) and their translucent corners showed black. The card has a 16 px radius and soft shadow, the same 24 px padding in every dialog, a header with the Techset mark, a kicker and a close button, and a soft footer band behind the buttons (Cancel first, the green action on the right). It re-centres when the window is resized and shrinks to fit a small window; while it is open the window behind takes no mouse input, Tab cycles inside the card, and window shortcuts (Ctrl+K, Ctrl+1 …) do nothing. Dialogs opened from a dialog stack on top. The import progress dialog is shown the same way (`embed()`); system file dialogs keep their native windows, and a dialog with no visible window (a start-up error) opens as a frameless window. `TSLG_NATIVE_DIALOGS=1` keeps plain native dialog windows everywhere. Drop-down lists tint and tick the chosen option, and date pickers show Monday-first weeks, today ringed in green, and Clear/Today links (`desktop_ui/popups.py`).

## 7. Asset inventory and provenance

SHA-256 values allow a maintainer to confirm that a local file still matches the researched asset.

| Local asset | Source | Format / dimensions | SHA-256 | Purpose |
|---|---|---|---|---|
| `assets/techset_logo.png` | Official monogram URL above | PNG, 250×250, RGBA | `cd06bda20eec2e1f97afca1769e080947f3be0a2d3fe7b50b091dbde97a443fc` | Header logo |
| `assets/techset_logo_with_text.png` | Official logo-with-text URL above | PNG, 250×250, RGBA | `ac431cdabc21359d3fa063ca25be266c89900ce3ff965bf3c23bcb4913741e4e` | Available official lockup |
| `assets/techset_favicon.ico` | Official favicon URL above | ICO, six embedded sizes up to 256×256 | `0aaa3ac2af05a0d48a033e26156e258f397f4b87549899d6a5fc44a0cb5a4b4f` | Desktop window icon |
| `assets/favicon.ico` | Copy of official favicon | ICO | `0aaa3ac2af05a0d48a033e26156e258f397f4b87549899d6a5fc44a0cb5a4b4f` | Conventional packaging alias |
| `assets/icon.png` | Copy of official monogram | PNG, 250×250, RGBA | `cd06bda20eec2e1f97afca1769e080947f3be0a2d3fe7b50b091dbde97a443fc` | Conventional packaging icon |
| `assets/fonts/PlusJakartaSans-Regular.ttf` | Static 400 instance of the [Google Fonts Plus Jakarta Sans](https://github.com/google/fonts/tree/main/ofl/plusjakartasans) variable font | TrueType | `2e4dd69f1bdfd50043664edce7ab2460f4e3a2e6707f2ccb644609b335c79650` | UI font |
| `assets/fonts/PlusJakartaSans-Medium.ttf` | Same source, 500 | TrueType | `521afad4d367745f4781577c9bdf682c4bb419cba64dd6f4eeb5afe3b72be17f` | UI font |
| `assets/fonts/PlusJakartaSans-SemiBold.ttf` | Same source, 600 | TrueType | `f2cb378268b1789d1d06d97d2db95df1976cf5d9125d444f17ebf91fdc1c25c7` | UI font |
| `assets/fonts/PlusJakartaSans-Bold.ttf` | Same source, 700 | TrueType | `b900920b5a33beb675a26caa0b6a5f9376635876d466985c3aef85c47842f95e` | UI font |
| `assets/fonts/PlusJakartaSans-ExtraBold.ttf` | Same source, 800 | TrueType | `ea1731bb89f81cedeeabead5e0939b26478b959d6dd22ab4f2b0d2523e133487` | UI font |
| `assets/fonts/JetBrainsMono-Regular.ttf` | Static 400 instance of the [Google Fonts JetBrains Mono](https://github.com/google/fonts/tree/main/ofl/jetbrainsmono) variable font | TrueType | `7d389bdcee2ff3a70703d82cd2e2bf0747ce8e309434b97d641146c458adf5c8` | IDs, times, paths |
| `assets/fonts/JetBrainsMono-Bold.ttf` | Same source, 700 | TrueType | `ed64ff1e4063024df0a34ab5864d4009f4e683d5e3679dd6d7ac39fdff953f07` | IDs, times, paths |
| `assets/fonts/OFL-PlusJakartaSans.txt` | Google Fonts Plus Jakarta Sans repository | SIL Open Font License text | `995c7199cab65954f545996326755daee7b63cc6b42b06c13da1f9502ab08a99` | Font license |
| `assets/fonts/OFL-JetBrainsMono.txt` | Google Fonts JetBrains Mono repository | SIL Open Font License text | `b2fe5e8987594e9ffd1d2ca52a2f5d73eb8335243893c5d6254b5ad69269591d` | Font license |
| `assets/fonts/Inter-Variable.ttf` | [Google Fonts Inter repository](https://github.com/google/fonts/tree/main/ofl/inter) | Variable TrueType | `29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031` | Former UI font; no longer loaded by the desktop UI |
| `assets/fonts/OFL.txt` | Google Fonts Inter repository | SIL Open Font License text | `5b9321a4298cfeb6b34354164a1c3afc3db114569984c502b9b35d988fd58c57` | Inter font license |

The older `fdt_logo*` files have been removed from the working tree. `assets/icons/{chevron_down,check,calendar}_{light,dark}.svg` and `chevron_down_disabled.svg` are application-drawn control indicators (drop-down, checkbox, date picker) referenced by the stylesheet, not brand assets. Every other UI icon is drawn at run time from the line-icon set in `desktop_ui/icons.py`.

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
| Line icons (navigation, buttons, chips) | `desktop_ui/icons.py` |
| Motion, modal shell, tab indicator, pop-ups | `desktop_ui/motion.py`, `desktop_ui/modal.py`, `desktop_ui/tab_motion.py`, `desktop_ui/popups.py` |
| Shell logo, wordmark, and tagline | `desktop_ui/main_window.py`, `desktop_ui/auth_pages.py` |
| In-app charts (native bar charts and bar lists) | `desktop_ui/widgets.py` (`BarChart`, `HBarList`) |
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
  assets/fonts/PlusJakartaSans-*.ttf \
  assets/fonts/JetBrainsMono-*.ttf \
  assets/fonts/OFL*.txt
```

## 14. Rights and licensing

The files downloaded from the Techset Solutions site remain brand assets owned or controlled by their respective rights holder. Their presence in the application does not grant broader trademark rights. Confirm deployment and distribution rights with the brand owner.

Plus Jakarta Sans, JetBrains Mono, and Inter are distributed under the SIL Open Font License, included at `assets/fonts/OFL-PlusJakartaSans.txt`, `assets/fonts/OFL-JetBrainsMono.txt`, and `assets/fonts/OFL.txt`. The repository currently does not contain a root license covering the application source code.
