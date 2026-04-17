# Sub-Plan 06.2 — Component Restyle Pass

**Status:** ⏳ Not started — **highest-priority sub-plan**
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Why this is first

Several mirageapp components are still **byte-identical (or ≤10-line diff) copies of their oldreddit versions**. Worse, `Toast` and `Tooltip` are REQUIRED theme components (see `src/registry/theme.js::REQUIRED_THEME_COMPONENT_KEYS`) and are rendered inside **every** mirageapp route. `Button` is imported by almost every route. Leaving them in oldreddit style means every "done" route is still visually contaminated.

Fixing these components first means every subsequent sub-plan benefits without per-route rework.

---

## Current audit

| Component | File | Diff vs oldreddit | Required? |
|---|---|---|---|
| Button | `components/Button.js` | 0 (identical) | used everywhere |
| Toast | `components/Toast.js` | 0 | ✅ required |
| Tooltip | `components/Tooltip.js` | 0 | ✅ required |
| InlineMedia | `components/InlineMedia.js` | 0 | feed/post |
| MediaGallery | `components/MediaGallery.js` | 0 | feed/post |
| UnlockPrompt | `components/UnlockPrompt.js` | 4 lines | ✅ required |
| MarkdownRenderer | `components/MarkdownRenderer.js` | 1 line | everywhere |
| QuestHeroCard | `components/QuestHeroCard.js` | 1 line | home |
| FilterBar | `components/FilterBar.js` | 31 lines (partial) | feeds |
| MediaAttachmentLayout | `components/MediaAttachmentLayout.js` | 33 lines (partial) | composers |
| MarkdownEditor | `components/MarkdownEditor.js` | 90 lines (partial) | composers |

`MobileBottomNav` is tracked separately in sub-plan 08 because the restyle is large.

---

## Goal

Bring every component in the audit in line with mirageapp RULES:

- R1 — single `bg` canvas (no `panel` fill on non-contained surfaces).
- R2 — color pairs; no hard-coded hex/rgb, no oldreddit accent blues.
- R3 — dividers use `border` (or `borderSubtle` / `headerBorder`).
- R5 — input focus style (no blue ring; neutral `borderStrong`).
- R6 — chevrons use `HiChevronDown`.
- R7 — font scale (buttons at `0.72–0.8rem`, inputs at `0.75rem/500`, no `font-weight: 800`).
- Mobile-app visual tone (spacing, icons, typography).

---

## Per-component requirements

### Button (`components/Button.js`)
- Mirror mobile app button system: primary (filled `followBtnBg`), secondary (outline `border` → `borderStrong` on hover), ghost (transparent → `hoverBg`), danger (uses `buttonDanger*` tokens), success (`buttonSuccess*`).
- Font: `0.72–0.8rem`, weight 500/600 per R7. No `700+`.
- Radius: small (6–8px), matching other pills.
- Focus: R5 (no blue ring).

### Toast (`components/Toast.js`)
- Container uses `panel` + `border` (lifted surface) per R2.
- Text `0.75rem/500`.
- Variants (info / success / warning / danger) use R2 tokens only.
- Dismiss icon via `react-icons/hi2`.

### Tooltip (`components/Tooltip.js`)
- Surface uses `menuBg` + `border` per R2.
- Text `0.62–0.65rem/500`.
- No custom shadow color — reuse panel shadow pattern.

### UnlockPrompt (`components/UnlockPrompt.js`)
- Panel uses `panel` + `border`; inputs follow R5 focus style.
- Buttons reuse the new restyled `Button`.
- Copy typography matches R7 (heading `1.1rem/700`, body `0.9rem/500`).

### InlineMedia + MediaGallery
- Containers sit on `bg` (R1). Frame/border uses `border` or `cardBorder`.
- Captions `0.62rem/500` `subtleText`.
- Lightbox overlay uses `overlay` token.

### MarkdownRenderer
- Paragraph `0.9rem/500`, code `0.8rem/500` using the mono family.
- Blockquote uses `borderSubtle` + `panelAlt` background.
- Links use `link` / `linkHover`.
- No hard-coded header sizes — headings use R7 scale.

### QuestHeroCard
- Hero surface may break R1 (hero is an explicit contrast surface) — use `gradient` token.
- Body text `0.9rem/500`, CTA uses restyled `Button`.
- Retire any raw `#667eea`/`#764ba2` references; they must come from `gradient`.

### FilterBar (finish pass)
- Confirm every button uses R5 focus + R7 font scale.
- Chevron uses `HiChevronDown` per R6.
- Dropdown uses `menuBg` / `menuSelectedBg`.

### MediaAttachmentLayout (finish pass)
- `MediaIconButton` already refactored to transparent pill with `feedCtrlHoverBg` — audit usages and drop any leftover `linear-gradient` or `box-shadow`.
- `MediaPreviewWrapper` border uses `border` with soft radius.

### MarkdownEditor (finish pass)
- Toolbar buttons transparent on `bg`; hover = `feedCtrlHoverBg`.
- Textarea follows R5 focus style.
- Preview toggle is a checkbox per R7.
- No blue ring anywhere.

---

## Scope

### In scope
- Rewrite or refactor the components listed above (see per-component requirements).
- Ensure all imports in `themes/mirageapp/index.js` still resolve.
- Update tokens in `tokens.js` only if a required color isn't yet available (document the new token in `RULES.md` R2 table).

### Out of scope
- Behavior/data changes.
- Icon library changes beyond `react-icons/hi2`.
- MobileBottomNav (see sub-plan 08).

---

## Verification checklist

- [ ] No file under `themes/mirageapp/components/` matches its `themes/oldreddit` counterpart exactly.
- [ ] `grep -r "#667eea\|#764ba2"` inside `themes/mirageapp/components/` returns 0 results (unless inside a `gradient` token reference).
- [ ] No `focusBlue` box-shadow ring on any input / textarea / pill-trigger.
- [ ] Every chevron uses `HiChevronDown`.
- [ ] Dark + light verified via theme toggle on a route that mounts each component (Home, CreatePost, Inbox, Settings, Profile placeholder, a post page).
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## PR description template

> Component restyle pass for `mirageapp`: Button, Toast, Tooltip, InlineMedia, MediaGallery, UnlockPrompt, MarkdownRenderer, QuestHeroCard are rewritten to use R1–R7 tokens/typography; finish passes on FilterBar, MarkdownEditor, MediaAttachmentLayout. Visual only. Closes sub-plan 06.2 and unblocks the remaining 06 sub-plans.
