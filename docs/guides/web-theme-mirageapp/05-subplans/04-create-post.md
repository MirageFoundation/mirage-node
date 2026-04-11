# Sub-Plan 05.4 — Create Post

**Route:** `/create_post`
**File:** `web/frontend/src/themes/mirageapp/routes/CreatePostView.js`
**Status:** ⏳ Not started
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

---

## Goal

Rewrite `mirageapp`'s `CreatePostView` as a panel-styled composer that matches the mobile app's tone, with a sticky `MarkdownEditor` toolbar on desktop and media attach row using theme tokens.

---

## References

- **Mobile:** `src/pages/create-screen.tsx`
- **Web (modern layout):** `web/frontend/src/themes/onyx/routes/CreatePostView.js`
- **Web (structure):** `web/frontend/src/themes/oldreddit/routes/CreatePostView.js`
- **Data hook (do not modify):** `useCreatePost`
- **Media helpers (reuse as-is):** `src/utils/ImageUpload.js`, `src/utils/VideoUpload.js`
- **Theme-local primitives:** `MarkdownEditor`, `TopicSelector`, `MediaAttachmentLayout`

---

## Scope

### In scope
- Rewrite `themes/mirageapp/routes/CreatePostView.js`.
- Style the composer panel, title/body inputs, and media attach row.
- Make the `MarkdownEditor` toolbar sticky on desktop.

### Out of scope
- `useCreatePost` or any submit flow change.
- Media upload logic (reuse `ImageUpload.js` / `VideoUpload.js`).
- `TopicSelector` internal logic (only restyle if needed).

---

## Requirements

- **Form container** styled as a panel (mobile-app tokens).
- **Topic selector** uses theme-local `TopicSelector`.
- **Title** and **body** inputs aligned with mobile-app typography.
- **`MarkdownEditor`** with **sticky toolbar on desktop** (scroll with content column).
- **Media attach row** styled with theme tokens — reuse `MediaAttachmentLayout`.
- **Submit button** uses theme's `Button` primary variant.
- **Validation / error states** styled consistently.
- Desktop width matches shell content column; mobile is full-bleed.
- Dark + light modes both work.
- No `themes/oldreddit/*` imports inside the new file.

---

## Suggested implementation steps

1. Read `themes/onyx/routes/CreatePostView.js` for modern layout reference.
2. Read `themes/oldreddit/routes/CreatePostView.js` for `useCreatePost` wiring.
3. Read mobile `src/pages/create-screen.tsx` for composer tone + order.
4. Copy the onyx structure (or oldreddit if simpler) into `themes/mirageapp/routes/CreatePostView.js`.
5. Wrap the form in a panel container with mobile tokens.
6. Wire `TopicSelector` from theme-local components.
7. Style title + body inputs with mobile typography.
8. Apply sticky toolbar to `MarkdownEditor` via CSS `position: sticky` on desktop breakpoint.
9. Style the media attach row with theme tokens.
10. Verify submit flow unchanged.
11. Build + manual smoke test with image + video upload.

---

## Verification checklist

- [ ] `/create_post` composes and submits successfully.
- [ ] Form container styled as a panel.
- [ ] `TopicSelector` renders and selects a topic.
- [ ] `MarkdownEditor` toolbar is sticky on desktop.
- [ ] Media attach row styled + image/video upload still works.
- [ ] Submit button uses theme `Button`.
- [ ] Dark + light modes verified.
- [ ] Desktop + mobile layouts verified.
- [ ] No `themes/oldreddit/*` imports.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## Risks

- **Media upload regression** → only reuse existing helpers; never reimplement upload logic.
- **Sticky toolbar layout shifts** → test at multiple viewport heights.
- **TopicSelector breakage** → if restyled, verify selection still updates form state.

---

## PR description template

> Rewrites `mirageapp`'s `CreatePostView` as a panel-styled composer with mobile-app typography, sticky `MarkdownEditor` toolbar on desktop, and themed media attach row. Visual only — `useCreatePost` and media upload helpers unchanged.
