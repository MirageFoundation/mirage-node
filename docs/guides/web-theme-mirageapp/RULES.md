# mirageapp Theme — Style Rules

**Source of truth for styling decisions in the `mirageapp` web theme.** Every sub-plan and every future UI change MUST follow these rules. When the user gives color/divider/layout instructions, consult this file first.

> This file grows over time. New rules get appended to the bottom with a date so history is preserved.

---

## R1 — Single background surface

The whole app reads as **one continuous canvas**. The main content background, feed background, header background, and route-level backgrounds all use the **same token**:

- **Token:** `theme.colors.bg`
- **Dark:** `#0d0f12`
- **Light:** `#FFFFFC`

### Rules

- ❌ Do **not** introduce a separate panel background for the main content column (feed / inbox / search / settings body / profile body / post detail body). They all sit on `theme.colors.bg`.
- ❌ Do **not** use `theme.colors.panel` or `theme.colors.panelAlt` as a full-page or full-column background.
- ✅ `panel` / `panelAlt` / `cardAlt` are only for **contained surfaces** that need to lift off the canvas: dropdown menus, popovers, modals, tooltips, highlighted rows (e.g., unread inbox row), and form inputs.
- ✅ TopBar + MobileHeader + Sidebar + content column **must share** the same canvas color. The only visual separator between them is the divider (see R3).
- ✅ When a card or row needs to "float", use a **subtle border** (R3) plus a small radius — not a different background — unless the component explicitly needs contrast (e.g., modal overlay).

### When this rule conflicts with existing code

If you find a route that paints its main column with `panel` as a background, treat it as a **bug** and fix it to `bg` during the sub-plan that touches that route. Call it out in the PR description.

---

## R2 — Color pairs (dark ↔ light)

When the user says _"change X in dark mode"_, find the token in the table below and **also** apply the paired light value. Same rule in reverse.

If the user gives a **raw hex/rgb value** instead of a token name, pick the matching token from this table and update both modes together. If no existing token fits, create a new one in `tokens.js` with both dark + light values and document it here.

### Base surfaces

| Token             | Dark             | Light               | Use                                                           |
| ----------------- | ---------------- | ------------------- | ------------------------------------------------------------- |
| `bg`              | `#0d0f12`        | `#FFFFFC`           | **The** canvas (R1). Page, header, feed, sidebar, shell.      |
| `text`            | `#fafafa`        | `#202329`           | Primary text.                                                 |
| `subtleText`      | `#98989D`        | `#6B7280`           | Secondary text, timestamps, metadata.                         |
| `textSecondary`   | `#98989D`        | `#4B5563`           | Secondary body text (paragraphs, descriptions).               |
| `panel`           | `#15181d`        | `#FFFFFF`           | Contained lifted surfaces only (menus, modals, tooltips).     |
| `panelAlt`        | `#1c2026`        | `#F7F8FA`           | Second-tier lifted surface (selected menu row, quote block).  |
| `surface`         | `#15181d`        | `#F7F8FA`           | Alias of `panel` for surface tiering.                         |
| `surface2`        | `#1c2026`        | `#EFF1F5`           | Alias of `panelAlt`.                                          |
| `surface3`        | `#232830`        | `#E5E7EB`           | Third tier (nested lifted surfaces).                          |
| `card`            | `#15181d`        | `#FFFFFF`           | Card-like components that need a lifted surface.              |
| `cardAlt`         | `#1c2026`        | `#F7F8FA`           | Alt card tier.                                                |
| `inputBackground` | `#1c2026`        | `#FFFFFF`           | Form input / select / textarea background.                    |
| `sidebarBg`       | `#15181d`        | `#FFFFFF`           | Sidebar-specific contained surfaces (not the sidebar column). |
| `headerBg`        | `#15181d`        | `#FFFFFF`           | Header-specific contained surfaces (not the header bar).      |
| `overlay`         | `rgba(0,0,0,.7)` | `rgba(0,0,0,.5)`    | Modal scrim.                                                  |

> ⚠️ Per R1 the **sidebar column**, **TopBar bar**, and **main feed column** itself still use `bg` — `sidebarBg` / `headerBg` are reserved for lifted sub-surfaces *inside* those regions.

### Borders & dividers

| Token          | Dark                | Light              | Use                                                    |
| -------------- | ------------------- | ------------------ | ------------------------------------------------------ |
| `border`       | `rgb(39, 40, 42)`   | `rgb(230, 230, 230)` | **App-wide divider & border.** See R3.               |
| `headerBorder` | `rgb(63, 65, 66)`   | `rgb(204, 204, 204)` | TopBar / MobileHeader bottom divider (stronger).     |
| `borderSubtle` | `#1f242b`           | `#EDEFF2`          | Very subtle internal divider inside cards.             |
| `borderStrong` | `#3a4049`           | `#9CA3AF`          | Emphasis border (focused input, hovered card).         |
| `cardBorder`   | `#2A2F36`           | `#E5E7EB`          | Card outline.                                          |
| `cardHoverBorder` | `#3a4049`        | `#9CA3AF`          | Card border on hover.                                  |

### Interactive accents

| Token              | Dark         | Light        | Use                                                    |
| ------------------ | ------------ | ------------ | ------------------------------------------------------ |
| `link`             | `#4285f4`    | `#4285f4`    | Link text. Same in both modes (mobile brand).          |
| `linkHover`        | `#6ba0fa`    | `#2563eb`    | Link hover.                                            |
| `focusBlue`        | `#4285f4`    | `#4285f4`    | Input focus rings, active indicators, unread dots.     |
| `accent`           | `#1c2026`    | `#F3F4F6`    | Neutral filled button background.                      |
| `accentHover`      | `#232830`    | `#E5E7EB`    | Neutral button hover.                                  |
| `accentDisabled`   | `#2A2F36`    | `#F3F4F6`    | Neutral button disabled.                               |
| `accentSubtle`     | `#15181d`    | `#F7F8FA`    | Subtle accent tile.                                    |
| `buttonText`       | `#fafafa`    | `#202329`    | Neutral button label.                                  |
| `scrollbar`        | `#4a4f57`    | `#C1C1C1`    | Scrollbar thumb.                                       |

### Hover surfaces

| Token              | Dark                     | Light                      | Use                                            |
| ------------------ | ------------------------ | -------------------------- | ---------------------------------------------- |
| `hoverBg`          | `rgb(25, 28, 31)`        | `rgb(246, 248, 249)`       | TopBar / Sidebar / menu item hover.            |
| `navActiveBg`      | `#1c2026`                | `#EFF1F5`                  | Active nav row background.                     |
| `menuBg`           | `rgb(25, 28, 31)`        | `rgb(255, 255, 255)`       | Popover / dropdown surface.                    |
| `menuSelectedBg`   | `rgb(44, 50, 54)`        | `rgb(230, 235, 238)`       | Selected dropdown option.                      |
| `menuItemHoverBg`  | `transparent`            | `rgb(246, 248, 249)`       | Dropdown row hover.                            |
| `menuItemHoverText`| `#FFFFFF`                | `rgb(34, 39, 42)`          | Dropdown row hover text.                       |
| `menuHeaderText`   | `rgb(187, 202, 211)`     | `rgb(95, 108, 115)`        | Dropdown header label.                         |
| `menuDangerText`   | `#FF7B70`                | `#FF6A5E`                  | Dropdown row danger label (block / delete).    |

### Votes / status

| Token          | Dark                         | Light                        | Use                                 |
| -------------- | ---------------------------- | ---------------------------- | ----------------------------------- |
| `voteUp`       | `#16A34A`                    | `#16A34A`                    | Upvote icon + success accent.       |
| `voteUpHover`  | `#22C55E`                    | `#15803d`                    | Upvote hover.                       |
| `voteUpBg`     | `rgba(22,163,74,0.18)`       | `rgba(22,163,74,0.12)`       | Upvote background tint.             |
| `voteDown`     | `#FF453A`                    | `#FF3B30`                    | Downvote icon + error/danger accent.|
| `voteDownHover`| `#ef4444`                    | `#DC2626`                    | Downvote hover.                     |
| `voteDownBg`   | `rgba(255,69,58,0.18)`       | `rgba(255,59,48,0.12)`       | Downvote background tint.           |

### Button variants

| Token                  | Dark                       | Light                      | Use                   |
| ---------------------- | -------------------------- | -------------------------- | --------------------- |
| `buttonDangerBg`       | `rgba(255,69,58,0.18)`     | `rgba(255,59,48,0.12)`     | Danger button bg.     |
| `buttonDangerBorder`   | `#993332`                  | `#FF3B30`                  | Danger button border. |
| `buttonDangerHoverBg`  | `rgba(255,69,58,0.28)`     | `rgba(255,59,48,0.2)`      | Danger hover.         |
| `buttonSuccessBg`      | `rgba(22,163,74,0.18)`     | `rgba(22,163,74,0.12)`     | Success button bg.    |
| `buttonSuccessBorder`  | `#2f5e3a`                  | `#16A34A`                  | Success button border.|
| `buttonSuccessHoverBg` | `rgba(22,163,74,0.28)`     | `rgba(22,163,74,0.2)`      | Success hover.        |

### Sidebar-specific

| Token                  | Dark                  | Light                   | Use                          |
| ---------------------- | --------------------- | ----------------------- | ---------------------------- |
| `sidebarItemText`      | `rgb(221, 228, 232)`  | `rgb(34, 39, 42)`       | Sidebar option text.         |
| `sidebarItemActiveText`| `#FFFFFF`             | `#000000`               | Active sidebar option text.  |
| `sidebarItemActiveBg`  | `rgb(44, 50, 54)`     | `rgb(230, 235, 238)`    | Active sidebar option bg.    |
| `menuBtnBorder`        | `rgb(134, 136, 137)`  | `rgb(128, 128, 128)`    | Sidebar collapse btn border. |
| `menuBtnBorderHover`   | `#FFFFFF`             | `#000000`               | Sidebar collapse btn hover.  |
| `menuBtnIcon`          | `#FFFFFF`             | `#000000`               | Sidebar collapse btn icon.   |

### Search & feed controls

| Token             | Dark                    | Light                    | Use                             |
| ----------------- | ----------------------- | ------------------------ | ------------------------------- |
| `inputIconColor`  | `rgb(143, 161, 172)`    | `rgb(95, 108, 115)`      | Inline input action icons.      |
| `inputIconHoverBg`| `rgb(53, 61, 65)`       | `rgb(221, 238, 232)`     | Inline icon hover tile.         |
| `feedCtrlText`    | `rgb(143, 161, 172)`    | `rgb(95, 108, 115)`      | Feed toolbar sort/view text.    |
| `feedCtrlHoverBg` | `rgb(53, 61, 65)`       | `rgb(221, 228, 232)`     | Feed toolbar hover tile.        |

### Follow button

| Token                 | Dark                | Light                   | Use                              |
| --------------------- | ------------------- | ----------------------- | -------------------------------- |
| `followBtnBg`         | `rgb(42, 90, 195)`  | `rgb(30, 67, 150)`      | Follow button default bg.        |
| `followBtnBgHover`    | `rgb(54, 110, 236)` | `rgb(21, 46, 104)`      | Follow button hover bg.          |
| `followBtnBorder`     | `rgb(140, 141, 143)`| `rgb(124, 125, 125)`    | "Following" state border.        |
| `followBtnBorderHover`| `#FFFFFF`           | `#000000`               | "Following" hover border.        |

### Post card action row

| Token                | Dark                | Light                   | Use                                |
| -------------------- | ------------------- | ----------------------- | ---------------------------------- |
| `actionIconBg`       | `rgb(44, 50, 54)`   | `rgb(230, 235, 238)`    | Block / share pill background.     |
| `actionIconHoverBg`  | `rgb(53, 61, 65)`   | `rgb(221, 228, 232)`    | Vote / comment / share pill hover. |

### Inbox rows

**Read rows are transparent** (sit on `bg`), unread rows get a lifted neutral tile. No per-row borders — row separation is handled by the feed divider (R3).

| Token                    | Dark                 | Light                 | Use                                |
| ------------------------ | -------------------- | --------------------- | ---------------------------------- |
| `inboxReplyUnreadBg`     | `rgb(34, 39, 42)`    | `rgb(239, 241, 243)`  | Unread row background tile.        |
| `inboxReplyReadBg`       | `transparent`        | `transparent`         | Read row (sits on `bg`).           |
| `inboxReplyUnreadBorder` | `transparent`        | `transparent`         | Reserved (borders via R3).         |
| `inboxReplyReadBorder`   | `transparent`        | `transparent`         | Reserved (borders via R3).         |
| `inboxReplyUnreadBgHover`| `rgb(44, 50, 54)`    | `rgb(230, 235, 238)`  | Unread row hover tile (= `sidebarItemActiveBg`). |
| `inboxReplyReadBgHover`  | `rgb(25, 28, 31)`    | `rgb(246, 248, 249)`  | Read row hover tile (= `hoverBg`). |
| `inboxMarkAllText`       | `rgb(221, 228, 232)` | `rgb(25, 28, 31)`     | "Mark all as read" rest text. Hover → `sidebarItemActiveText`. |
| `inboxHighlightRail`     | `#FACC15`            | `#D97706`             | Inbox-linked comment left-rail accent (yellow/amber). |
| `inboxHighlightBg`       | `rgba(250,204,21,0.06)` | `rgba(217,119,6,0.08)` | Inbox-linked comment subtle background tint. |

### Reply composer

| Token                 | Dark                | Light                | Use                                                |
| --------------------- | ------------------- | -------------------- | -------------------------------------------------- |
| `composerPreviewBg`   | `rgb(26, 28, 31)`   | `rgb(246, 248, 249)` | Live-preview tile inside the reply composer.       |
| `pickerBg`            | `rgb(25, 28, 31)`   | `rgb(246, 248, 249)` | Sticker / GIF picker popover surface.              |

### Brand gradient

| Token           | Dark / Light (shared)                             | Use                                    |
| --------------- | ------------------------------------------------- | -------------------------------------- |
| `gradientStart` | `#667eea`                                         | Gradient start.                        |
| `gradientEnd`   | `#764ba2`                                         | Gradient end.                          |
| `gradient`      | `linear-gradient(135deg, #667eea 0%, #764ba2 100%)`| Primary CTA + accent border gradient.  |

### Workflow when the user gives a color

1. **Try to match a token** in the table above (search by use-case first, then by hex).
2. If matched → update both dark and light values in `web/frontend/src/themes/mirageapp/tokens.js` so the pair stays consistent. Update this table too.
3. If no token matches → **create a new token** with both dark + light values, add it to `tokens.js`, document it in this table, and then use it in the component.
4. Never hard-code a raw hex/rgb in a styled-component. Always go through a token so dark/light parity is preserved.

---

## R3 — Divider rule

The **feed divider** (the 1px line between rows in the post feed / inbox / lists) is the single divider style used across the entire theme.

- **Token:** `theme.colors.border`
- **Width:** `1px`
- **Style:** `solid`
- **Example:** `border-bottom: 1px solid ${({ theme }) => theme.colors.border};`

### Rules

- ✅ When the user says _"use the same divider as the feed"_, use exactly `1px solid theme.colors.border`.
- ✅ TopBar / MobileHeader bottom divider may use `headerBorder` (slightly stronger) — this is the only allowed variation.
- ❌ Never use custom hex/rgb/rgba values for dividers.
- ❌ Never use double borders, dashed borders, or gradients for dividers.
- ❌ Never invent ad-hoc divider colors with inline `rgba(...)` — use `borderSubtle` if a weaker divider is needed inside a card, otherwise use `border`.

### Allowed divider variants

| Use case                                           | Token          |
| -------------------------------------------------- | -------------- |
| Feed row / inbox row / list row divider            | `border`       |
| TopBar / MobileHeader bottom edge                  | `headerBorder` |
| Very subtle internal divider inside a single card  | `borderSubtle` |

---

## R4 — Reference check before changing any UI

**Every UI change to `mirageapp` must be preceded by reading both of these references**:

1. **Web (data + structure):** the matching view in `web/frontend/src/themes/bluemoon/`
   - Example: changing `InboxView.js` → read `themes/bluemoon/routes/InboxView.js` first.
   - Use bluemoon as the **canonical source for data shape, hook wiring, and feature coverage**. Every piece of data bluemoon shows must be shown in mirageapp too.
2. **Mobile (visual / interaction language):** the matching screen in `mirage-mobile-app/src/pages/` (or `app/(tabs)/`).
   - Example: Inbox → `src/pages/inbox-screen.tsx`.
   - Use mobile as the **canonical source for visuals**: spacing, typography, tokens, row layout, icons, empty state tone, interaction feel.

### The hybrid rule

When mobile visuals and bluemoon data coverage conflict:

- **Data / features / hook wiring** → follow **bluemoon**. Do not drop any feature that bluemoon shows.
- **Look, feel, spacing, typography, tokens, icons** → follow **mobile**.
- **Desktop layout structure** → Plan 02 shell (TopBar + Sidebar + content column).

### Process (do this every sub-plan)

1. Read the bluemoon version of the route.
2. Read the mobile version of the screen.
3. List the data fields bluemoon displays → these must all appear in mirageapp.
4. Port visuals from mobile (spacing, tokens, row layout, icons, typography).
5. Wrap the result in the Plan 02 desktop shell.
6. Verify the build passes.

> If bluemoon doesn't have an equivalent (new surface), fall back to the oldreddit theme for structure, then apply mobile visuals.

---

## Quick-reference checklist (every UI change)

Before opening a PR for any mirageapp change, confirm:

- [ ] Main background uses `theme.colors.bg` (R1) — no page-level `panel` fill.
- [ ] Every new color came from the R2 table (or a new token with both dark + light values).
- [ ] Dividers use `theme.colors.border` (or `headerBorder` / `borderSubtle` per R3).
- [ ] All inputs follow R5 focus style (`borderStrong` hover + focus, no blue ring).
- [ ] All chevrons use `HiChevronDown` per R6 — no unicode, no inline polyline.
- [ ] Typography follows R7 — inputs at `0.75rem/500`, page heading at `1.1rem/700`, no `>1.1rem` body text, no `font-weight: 800`.
- [ ] I read the bluemoon version of this view before changing it (R4).
- [ ] I read the mobile version of this screen before changing it (R4).
- [ ] All bluemoon data fields are present in mirageapp.
- [ ] Mobile visual tone (spacing, typography, icons) applied.
- [ ] No `themes/oldreddit/*` or `themes/bluemoon/*` imports inside `themes/mirageapp/*`.
- [ ] Dark + light modes both verified manually in the browser.
- [ ] `CI=true npm run build` passes cleanly in `web/frontend`.

---

## R5 — Input focus style (no blue ring)

The comment composer's textarea is the **canonical input focus style** for the entire theme. Every input / textarea / select / pill-trigger in `mirageapp` MUST follow it.

### Rules

- **Rest border:** `1px solid theme.colors.border`
- **Hover border:** `theme.colors.borderStrong`
- **Focus border:** `theme.colors.borderStrong` (NOT `focusBlue`)
- **Focus box-shadow:** `none` (no blue ring, no `accentSubtle` ring)
- **Background:** `theme.colors.bg` (inputs sit on the canvas, per R1)
- **Outline:** `none`
- **Placeholder color:** `theme.colors.subtleText`

### Concrete snippet

```css
border: 1px solid ${({ theme }) => theme.colors.border};
background: ${({ theme }) => theme.colors.bg};
color: ${({ theme }) => theme.colors.text};

&:hover:not(:disabled) {
    border-color: ${({ theme }) => theme.colors.borderStrong};
}
&:focus {
    outline: none;
    border-color: ${({ theme }) => theme.colors.borderStrong};
    box-shadow: none;
}
&::placeholder {
    color: ${({ theme }) => theme.colors.subtleText};
}
```

### Why

`focusBlue` is reserved for **active indicators** (selected tab underline, unread dot, active link). Using it as a focus ring on every input makes the whole theme feel "Reddit blue"; the mirageapp visual language is neutral / monochrome with blue as an accent, not a background.

### Applies to

All text inputs, textareas, selects, searchable selectors (`TopicSelector`), pill toggles (`TagPill`, "Add content warning"), community pickers, comment composer, create-post composer, inline editors, settings inputs.

### Exceptions

- Submit / primary-action buttons may use `followBtnBg` (solid blue pill) — that's a filled state, not a ring.
- Validation error state may use `voteDown` border + shadow.

---

## R6 — Chevron icon

The single chevron icon across the whole theme is `HiChevronDown` from `react-icons/hi2`.

### Rules

- ❌ Do **not** use `▼`, `▽`, `⌄`, emoji chevrons, or custom inline SVG polyline chevrons.
- ❌ Do **not** import chevrons from other icon packs (`react-icons/fi`, `react-icons/fa`, `lucide-react`, etc.).
- ✅ Always: `import { HiChevronDown } from "react-icons/hi2";`
- ✅ Wrap in a `ChevronWrap` span that rotates on expand/active:

```jsx
const ChevronWrap = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: transform 0.15s ease;
    transform: rotate(${({ $expanded }) => ($expanded ? "180deg" : "0deg")});
`;
```

- ✅ Icon size: typically `0.85rem` – `1rem`, matching surrounding text.
- ✅ Color: inherit from parent — never hard-coded.

### Existing references

- `themes/mirageapp/ListFeedView.js` — sort / view / expand chevrons.
- `themes/mirageapp/components/Sidebar.js::ChevronIcon` — topic expand chevron.
- `themes/mirageapp/routes/SettingsView.js::ChevronPill` — settings row chevron.

### When adding a new chevron

Reuse one of the existing `ChevronWrap` / `ChevronIcon` patterns. Do not re-roll an inline SVG.

---

## R7 — Font scale (sizes and weights)

The theme uses a **compact type scale**. Most of the app lives between `0.6rem` and `0.8rem`. Do NOT default to `1rem` / `1.1rem` / `0.95rem` / `0.9rem` for form controls or labels just because they look clean in isolation — they don't match the rest of the theme and instantly read as "oversized".

### Size scale

| Token size | Weight                 | Use                                                                          |
| ---------- | ---------------------- | ---------------------------------------------------------------------------- |
| `0.55rem`  | 500 / 600              | Eyebrow labels (uppercase caps), tiny section labels inside dropdowns.       |
| `0.6rem`   | 400 / 500              | Micro metadata, tiny counters, picker hint text.                             |
| `0.62rem`  | 400 / 500              | Time-ago stamps, byline metadata, character-count hints.                     |
| `0.65rem`  | 500 / 600              | Small labels, small helper text, "mark all as read" style actions.           |
| `0.68rem`  | 500 / 600              | Unread counts, compact pill labels, inbox meta.                              |
| `0.7rem`   | 400 / 500 / 600        | **Default input / textarea / select / tag pill / subtle help text.**         |
| `0.72rem`  | 500 / 600              | Button labels (small), nav row text.                                         |
| `0.75rem`  | 500 / 600              | Primary button labels, medium density labels.                                |
| `0.78rem`  | 500 / 600              | Sidebar row text, radio labels.                                              |
| `0.8rem`   | 500 / 600              | Emphasized label, primary CTA pill text, tab label (compact).                |
| `0.85rem`  | 600 / 700              | Sub-section heading, prominent row title in a list.                          |
| `0.9rem`   | 500 / 600              | Body markdown text, post-details copy.                                       |
| `1.1rem`   | 700                    | **Page title / route heading** (e.g. Inbox, Settings, Create post).          |
| `>1.1rem`  | —                      | Reserved for hero/welcome surfaces. Do not use on regular route headings.    |

### Weight scale

- **400** — plain body paragraphs.
- **500** — default for most UI text (inputs, links, row labels).
- **600** — buttons, tag pills, row titles, labels, active states. Most common weight in the theme.
- **700** — page heading only, strong emphasis within copy, inbox `HeaderTitle`.
- **800+** — forbidden unless explicitly requested by design.

### Inputs (all composer/form inputs in one place)

All input-like controls — text inputs, textareas, selects, pill triggers, tag pills, search inputs, floating-label inputs — MUST use:

- `font-size: 0.75rem;` (single canonical input size across the theme)
- `font-weight: 500;` (for the typed value)
- placeholder: same 0.75rem / 500, colour `subtleText`
- floating label / helper copy inside an input: `0.62rem` / 500 / `subtleText`

This keeps every form block (Create Post title, body, link URL, tag select, TopicSelector, comment composer textarea, inbox search, etc.) at the **same typographic weight** regardless of which component renders it.

### Route / page heading

All route-level headings match `InboxView::HeaderTitle`:

```
font-size: 1.1rem;
font-weight: 700;
letter-spacing: -0.01em;
```

This is the canonical "page heading" style. Don't invent a bigger `<h1>` just because it's a composer.

### Common mistakes

- ❌ `font-size: 1.6rem; font-weight: 800;` for "Create post" heading → use the 1.1rem/700 page heading style.
- ❌ `font-size: 0.95rem;` for a title input → use 0.75rem/500 like every other input.
- ❌ `font-size: 0.9rem;` for a "drag and drop" empty state → should be 0.7rem/500 (subtle helper copy).
- ❌ `font-weight: 700;` on a tab label → use 600 (500 for inactive, 600 for active) at 0.75rem.

---

## Changelog

| Date       | Change                                     |
| ---------- | ------------------------------------------ |
| 2026-04-12 | Initial rules: R1 bg, R2 pairs, R3 divider, R4 reference check. |
| 2026-04-12 | Fixed `Layout.js::ContainerBody` to use `bg` instead of `panel` (R1). Updated inbox row tokens to mobile-app style (transparent read, primary-blue unread). |
| 2026-04-12 | Inbox unread tokens switched from primary-blue tint to lifted neutral tile: dark `rgb(34,39,42)` / `rgb(44,50,54)` hover, light `rgb(239,241,243)` / `rgb(230,235,238)` hover. |
| 2026-04-12 | Reply composer polish: new `composerPreviewBg` token (dark `rgb(26,28,31)` / light `rgb(246,248,249)`). Flattened `MediaIconButton`, `StickerPicker::PickerButton`, `GifPicker::PickerButton` (removed `linear-gradient(135deg, #667eea, #764ba2)` + box-shadows; now transparent → `feedCtrlHoverBg` on hover, 28x28). Composer textarea now sits on `bg` with neutral `borderStrong` focus (no blue ring). Custom checkbox for Preview toggle. Submit button: flat `focusBlue` pill, weight 500. Cancel button (data-mirageapp-cancel): ghost pill, weight 500. |
| 2026-04-12 | Sticker / GIF picker polish: new `pickerBg` token (dark `rgb(25,28,31)` / light `rgb(246,248,249)`). Sticker pack tabs now text-only (no pill bg). GIF launcher icon redrawn (cleaner rounded-rect with centered "GIF" text). Close button moved into header rows as a real flex sibling so input/title and `×` share vertical center. Submit button color changed from `focusBlue` → `followBtnBg` to match the topic Follow pill across the theme. |
| 2026-04-16 | Post Details Iteration 2: new `inboxHighlightRail`/`inboxHighlightBg` token pair (retired raw `#FACC15`). Comments header row with count. Chevron collapse affordance. `ActionButton` pills matched to 32px `VoteSection::PillRoot` height, `feedCtrlText` rest color. Composer padding tightened. StateBlock pattern for loading/error/empty states. LoggedOutPromptCard for guest users. Block/success/confirm messages routed through R2 tokens. Comment sort controls removed (R4 — not in bluemoon). `CompactExpandedBody` font tightened to 0.7rem/0.64rem with `contentFontFamily`. |
| 2026-04-17 | Added R5 (input focus style — neutral `borderStrong`, no blue ring) and R6 (chevron icon — `HiChevronDown` only). Applied R5 + R6 to `TopicSelector` (pill style with `HiChevronDown`, no `#667eea` border/shadow, `panelAlt` dropdown rows instead of raw rgba). Restyled `CreatePostView` with Text / Images & Video / Link tabs, compact `TagPill`, radio-style content warning picker (`RadioInput`/`RadioLabel`), 720px capped width matching Inbox, transparent toolbar buttons scoped via `data-mirageapp-editor`, followBtnBg submit button and preview toggle. |
| 2026-04-17 | Added R7 (font scale). CreatePostView pass 2: "Create post" heading matches InboxView (1.1rem/700) with inbox-style header row; tabs at 0.75rem (500 / 600 active); `TitleShell`/`LinkShell`/`TagPill`/inputs unified to 0.75rem/500 with 0.62rem/500 floating labels; "Save Draft" + "Post" buttons share a 1.85rem height; removed `TierBadge`; moved sticker / GIF pickers out of Text tab into a single unified `MediaToolbar` row below the editor; inline `MediaIconButton`s now transparent on `bg` canvas; rebuilt `ImageCarouselTile` (Add / delete / prev-next arrows) matching Reddit reference; editor body shell is now border-less and background-less so the textarea sits flush on canvas. `TopicSelector`: removed `r/` badge, trigger/search share height (2.1rem), relabelled "Select a topic", dropdown now uses `menuBg`/`menuSelectedBg` tokens and `sidebarItemText` rows matching the global `SearchDropdown` sheet. |
| 2026-04-29 | `MarkdownEditor::MentionDropdown` (`@username` autocomplete used by both the comment composer and the Create Post body) restyled to match the canonical `SearchDropdown` sheet pattern: `menuBg` surface with `border` outline at `12px` radius (was raw `surface3` + `borderSubtle` at `6px`), shared `0 12px 32px rgba(0,0,0,0.28)` shadow, `scrollbar` token, `min(60vh, 320px)` cap. Rows now use the `SearchDropdown` row contract (`sidebarItemText` rest → `menuSelectedBg` + `menuItemHoverText` on hover) with a 28px gradient avatar tile (initial letter, `gradient` bg, `buttonText`) and a two-line text column: `MentionUsername` `0.7rem/600`, `MentionAddress` `0.6rem/500` `subtleText` (R7). New `MentionHeader` row (`Mention` eyebrow `0.55rem/500` uppercase `menuHeaderText` + `MentionQueryBadge` pill `accent` bg / `focusBlue` text `0.6rem/600`) mirrors the mobile `mention-suggestions.tsx` "Results for `@query`" affordance (R4). `MentionHint` rows redesigned as flex rows with `HiOutlineMagnifyingGlass` icon + `0.65rem/500` `subtleText` copy (no italic). Address shortened to `8…4` chars to match the mobile reference. No new tokens added — every color comes from existing R2 tokens. |
