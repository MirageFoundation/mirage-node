# Sub-Plan 06.2 — Component Restyle Pass

**Status:** ✅ Done
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Ship plan

This sub-plan covered the "globals" component restyle: the REQUIRED theme components plus `Button`, which is imported by almost every route.

| Slice | Components | Status |
|---|---|---|
| A — Globals (required + Button) | Button, Toast, Tooltip, UnlockPrompt | ✅ Done |

> **Note:** Two additional slices were originally scoped and later dropped by design decision. Those components stay as-is; any future restyle work on them will be scoped as a separate plan.
>
> - **Slice B** (content rendering — MarkdownRenderer, InlineMedia, MediaGallery) — dropped.
> - **Slice C** (composer / feed controls — FilterBar, MediaAttachmentLayout, MarkdownEditor) — dropped.

### Slice A notes

- **Button** — variants rebuilt on R2 tokens: primary uses `followBtnBg`/`followBtnBgHover`, primaryDanger uses `voteDown`/`voteDownHover`, ghost uses `hoverBg`, subtle uses `accent`. All hard-coded `#667eea`/`#764ba2`/`#dc2626`/`#22c55e`/`#10b981`/`#f59e0b` removed. Focus-visible = neutral `borderStrong` (R5). Sizes tightened to R7 (xs `0.65rem` / sm `0.72rem` / md `0.78rem` / lg `0.85rem` / pill `0.75rem`). Radii normalized (6–8px / 999px for pill). Removed `translateY(-1px)` lift and `box-shadow` glows. `warning` variant now maps to danger tokens (most call-sites are destructive confirms). Public API unchanged (same props, same variant names — `primary` / `primaryDanger` / `secondary` / `danger` / `success` / `warning` / `ghost` / `subtle` / `link`).
- **Toast** — typography to `0.75rem/500` (R7), radius `8px`, alert variant uses `buttonDangerBg` + `voteDown` text + `buttonDangerBorder` (drops raw `#b91c1c` / `#fecaca`). Animation + spinner logic unchanged.
- **Tooltip** — surface moves to `menuBg` (R2 popover token), typography to `0.65rem/500` (R7), radius `6px`, theme-aware shadow (light = subtle, dark = stronger). Auto-positioning logic unchanged.
- **UnlockPrompt** — overlay uses `overlay` token (was raw rgba). Input follows R5 focus style (sits on `bg`, neutral `borderStrong`). Button uses `followBtnBg`/`followBtnBgHover` (was raw `#3b82f6`). Error text uses `voteDown` token. Lock glyph swapped from entity to `HiLockClosed` (R6 friendly). Page heading at `1.1rem/700`, subtitle `0.78rem/500` (R7). Behavior (seedVault.unlock, passkey fallback, handleKeyDown) unchanged.

---

## Why this mattered

Several default components were **byte-identical (or ≤10-line diff) copies of their oldreddit versions**. `Toast` and `Tooltip` are REQUIRED theme components (see `src/registry/theme.js::REQUIRED_THEME_COMPONENT_KEYS`) and are rendered inside **every** default route. `Button` is imported by almost every route. Leaving them in oldreddit style meant every "done" route was still visually contaminated.

Fixing these components first means every subsequent sub-plan benefits without per-route rework.

---

## Current audit

| Component | File | Diff vs oldreddit | Required? |
|---|---|---|---|
| Button | `components/Button.js` | restyled | used everywhere |
| Toast | `components/Toast.js` | restyled | ✅ required |
| Tooltip | `components/Tooltip.js` | restyled | ✅ required |
| UnlockPrompt | `components/UnlockPrompt.js` | restyled | ✅ required |

`MobileBottomNav` is tracked separately in sub-plan 08 because the restyle is large. `MarkdownRenderer`, `InlineMedia`, `MediaGallery`, `FilterBar`, `MediaAttachmentLayout`, and `MarkdownEditor` are intentionally out of scope for this sub-plan.

---

## Goal

Bring every component in the audit in line with default RULES:

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

---

## Scope

### In scope
- Rewrite or refactor the components listed above (see per-component requirements).
- Ensure all imports in `themes/default/index.js` still resolve.
- Update tokens in `tokens.js` only if a required color isn't yet available (document the new token in `RULES.md` R2 table).

### Out of scope
- Behavior/data changes.
- Icon library changes beyond `react-icons/hi2`.
- MobileBottomNav (see sub-plan 08).
- Content-rendering components (MarkdownRenderer, InlineMedia, MediaGallery).
- Composer / feed control components (FilterBar, MediaAttachmentLayout, MarkdownEditor).

---

## Verification checklist

- [x] Slice A components under `themes/default/components/` no longer match their `themes/oldreddit` counterparts.
- [x] No `focusBlue` box-shadow ring on any Slice A input / textarea / pill-trigger.
- [x] Dark + light verified via theme toggle on a route that mounts each component.
- [x] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## PR description template

> Component restyle pass for `default` (Slice A): Button, Toast, Tooltip, UnlockPrompt rewritten to use R1–R7 tokens/typography. Slice B (content rendering) and Slice C (composer / feed controls) intentionally out of scope. Visual only. Closes sub-plan 06.2.
