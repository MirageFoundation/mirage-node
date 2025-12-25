# Writing Update Docs

Release notes live in `docs/updates/update_vX.Y.Z.md`.

## Structure

```markdown
# Mirage vX.Y.Z Release Notes

### Overview

2-3 paragraphs of marketing/philosophy. This is the hook. Explain what the release
is about, why it matters, and how it improves the user experience. Write like you're
pitching to someone who's never heard of Mirage.

---

### Feature Name

- Bullet points
- Keep it concise
- No fluff

---

### Another Feature

- More bullets
- User-facing changes only

---

### Bug fixes

- One line per fix
- What was broken, now it works

---

### For developers

- API changes
- New components
- Migration names
```

## Rules

1. **One header style**: Use `###` for all sections. No mixing `##` and `###`.

2. **Overview is everything**: The Overview section should contain the marketing pitch, philosophy, and key highlights. Someone reading only the Overview should understand what this release is about.

3. **Be concise**: Bullet points for features and fixes. No verbose explanations. If it takes more than one line, it's too long.

4. **Skip the metadata**: No version/codename blocks at the top. The filename and title already contain the version.

5. **Separate with `---`**: Use horizontal rules between sections for visual clarity.

6. **Developer section last**: Technical details (API endpoints, component names, migration keys) go at the bottom for developers who need them.

7. **Don't document everything**: Skip trivial changes. Focus on what users and developers actually care about.

## Example

See `docs/updates/update_v1.6.3.md` for the current format.

