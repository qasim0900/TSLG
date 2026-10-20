# UI/UX and accessibility audit

Audit date 2026-10-20. Every page was reviewed in light and dark themes at 1360 × 860, 980 × 720, and 760 × 600 px (the minimum), offscreen and on the native Wayland session (DPR 1.0).

## Brand reference

The official site (techsetsolutions.com) renders client-side, so its compiled stylesheets were downloaded and searched directly. Present: `#39B54A`, `#FFCB4A`, `#0A1414`, `#FBFAF8`, `#0A1D3B` (as `bg-[#0a1d3b]`), `#C3C6CE`, `#F5F5F5`, `#32CD32`, and the Inter typeface. These match the tokens recorded in [BRANDING.md](../BRANDING.md), which now notes this re-verification. No new brand color, logo, or font was introduced; the only new assets are three application-drawn drop-down chevrons.

**Design decision reverted:** during the audit the dark-theme table-header color `#0A1D3B` was briefly replaced with a teal neutral for aesthetic reasons. Because `#0A1D3B` is a verified official color, that change was reverted.

## Findings and changes

| Area | Finding | Change | Defect |
|---|---|---|---|
| Sidebar | "Techset LeadGen" clipped to "Techset LeadG"; tagline cut off | Logo 36 px, name 18 px, tagline 12 px; full text fits | DEF-010 |
| Navigation icons | Unrelated stock icons; Sales arrow invisible on the dark sidebar, where compact mode shows icons only | Painted line icons (grid, trend, funnel, people) in the active text color, recolored on theme change | DEF-016 |
| Theme toggle | Read "Dark mode" while already dark after a restart | Label follows the actual theme | DEF-015 |
| Dashboard | Data-status sentence scrambled by an Urdu month name | Locale-independent English dates everywhere, including reports | DEF-007 |
| Dashboard | Card titles at different heights in one row | Card contents top-aligned | — |
| Leads filters | Three drop-downs all read "All" with no label | Visible labels: Search, Source, Stage, Period | DEF-011 |
| Leads and Clients layouts | Empty half-width columns, stretched "Add client" after resizing | Column stretch reset on reflow | DEF-012 |
| Tables | View/Edit/Delete buttons overflowed rows; "Delete" in dark mode about 2.5:1 | Painted buttons sized to 36 px rows; dark-mode destructive color `#FFB4AB` | DEF-008, DEF-014 |
| Tables | Numbers sorted as text; tables opened in Z–A or ID order | Value-based sorting; meaningful default orders | DEF-006 |
| Inputs | No drop-down arrows; disabled fields looked enabled | Chevron indicators; muted disabled fill and text | DEF-013 |
| Sales filters | Quick-range buttons stretched to half the page width | Compact chips in one row | — |
| Sales filters | "Any date" calendar opened on January 1900 | Opens on the current month | DEF-023 |
| Sales page | Horizontal scrolling at the minimum window size | Charts shrink with the window | DEF-009 |
| Client form | Validation error closed the form and lost input | Inline error, input kept, Save disabled while saving | DEF-005 |
| Errors | Two identical dialogs per error | One dialog, owned by the shell | DEF-004 |
| Feedback text | Error and warning status lines had no styling | Error and warning colors on status lines and form errors | — |
| Lost features | No spend editor, top clients, or marketing summary after the migration | Restored | DEF-020–022 |
| User data | Names that looked like HTML were formatted | Plain-text rendering | DEF-025 |

## Accessibility

### Contrast (WCAG 2.2; computed from the token values)

| Pair | Ratio | Requirement |
|---|---:|---|
| White on primary green `#287D35` (light theme buttons) | 5.15:1 | 4.5:1 text |
| Ink on official green `#39B54A` (dark theme buttons) | 7.02:1 | 4.5:1 text |
| Muted text `#62637A` on canvas `#FBFAF8` | 5.6:1 | 4.5:1 text |
| Error text `#BA1A1A` on canvas | 6.2:1 | 4.5:1 text |
| Warning text `#7A5900` on canvas | 6.2:1 | 4.5:1 text |
| Dark-mode destructive `#FFB4AB` on the dark table base | about 10:1 | 4.5:1 text |

### Keyboard focus (DEF-024; measured on rendered pixels)

Before the fix, focused navigation, primary, gold, and red buttons drew their focus border in their own fill color, so nothing visibly changed; gold rings on white inputs measured about 1.5:1. After:

| Control | Light theme | Dark theme |
|---|---:|---:|
| Navigation button | 5.15:1 | 10.79:1 |
| Selected navigation button | 3.41:1 | 7.02:1 |
| Primary button | 3.41:1 | 7.02:1 |
| Secondary button | 3.02:1 | 6.17:1 |
| Destructive button | 4.27:1 | 5.88:1 |
| Text input | 3.02:1 | 6.17:1 |

Ratios compare each control's edge pixel unfocused and focused; 3:1 is the WCAG 2.2 minimum. `test_def024_…` enforces this for both themes.

### Keyboard operation (verified)

Ctrl+1–4 switch pages, Ctrl+I imports, Ctrl+F focuses search on Leads and Clients, Ctrl+N adds a client, Ctrl+E exports leads, and F5 refreshes Leads and Clients. In tables, Enter or double-click opens the record, the context menu (right-click, Menu key, or Shift+F10) offers every row action, and Delete deletes the selected client after confirmation.

### Not verified

- Screen readers: pages, tables, KPI cards, painted row actions (through `AccessibleTextRole`), and dialogs carry accessible names and descriptions, but no screen reader was run.
- Reduced motion: the UI has no animations beyond Qt's native feedback, so there is nothing to reduce.
- Scaling above DPR 1.0 was not available. Icons are rendered at 2× and the layout uses layouts rather than fixed positions, but this was not observed.

## Remaining UX observations

See OPEN-01, OPEN-05, and OPEN-06 in [DEFECT_LOG.md](DEFECT_LOG.md): zero-spend ratios shown as €0.00 per source, no bulk "Clear spend", and the squeezed first column of wide tables at narrow widths. The top bar repeats the page name shown in each page's heading; this is common in desktop apps and was left unchanged.
