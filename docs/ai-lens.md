# AI Lens: Client-Side Feed Transformation

## Overview

AI Lens is a client-side feature that lets users transform their Mirage feed through LLM processing. Users provide their own API key (e.g., Google Gemini free tier), configure transformation rules, and the app processes posts locally before rendering. The blockchain and backend are untouched — this is purely a frontend feature.

## Why Client-Side

- **No server liability.** Mirage never stores or proxies API keys. Keys live on the user's device.
- **No backend changes.** The app fetches raw posts as normal, then transforms them before display.
- **No infrastructure cost.** LLM calls go directly from the user's device to the provider. Mirage servers see zero additional load.
- **Privacy aligned.** Mirage-the-company never sees what transformations a user runs or what the AI returns.
- **Blockchain stays clean.** Original posts remain immutable on-chain. Transformations are ephemeral, per-user rendering decisions.

## How It Works

1. User enters an LLM API key in app settings (stored in device-local secure storage)
2. User configures one or more transformation rules (e.g., "translate non-English posts", "add fact-check notes", "what would Naval Ravikant say about this")
3. App fetches raw posts from the Mirage backend
4. App sends each post through the user's transformation pipeline, calling the LLM API directly from the client
5. Transformed content renders in place of (or alongside) the original

```
┌──────────┐      ┌──────────────┐      ┌─────────────┐
│  Mirage  │─────▶│  App Client  │─────▶│  LLM API    │
│  Backend │ raw  │  (frontend)  │ post │  (Gemini,   │
│          │posts │              │◀─────│   OpenAI)   │
└──────────┘      │  render the  │ xfm  └─────────────┘
                  │  transformed │
                  │  result      │
                  └──────────────┘
```

The backend never participates in the transformation. The API key never leaves the device.

## Transformation Types

### Replace (Utility)
The original content is visually replaced with the transformed version. The user sees only the result.

- Translation (Portuguese → English)
- Tone adjustment ("rewrite this post to be neutral and factual")
- Summarization (condense long posts into a paragraph)

A subtle indicator (icon or label) should signal that the displayed content has been transformed, with a tap to reveal the original.

### Amend (Commentary)
The original content is preserved. A note is appended below it, styled like X's Community Notes.

- Personality takes ("What would Charlie Kirk / Naval / AOC say about this?")
- Fact-checking ("Verify claims in this post")
- Context enrichment ("Add current stock price for any tickers mentioned")

### Pipeline Composability
Because transformations happen sequentially on the client, they compose naturally. A user can run:

1. Translate from any language → English
2. Fact-check the English version
3. Append Naval Ravikant's take

Each step receives the output of the previous step. No conflict resolution needed — it's the user's own pipeline running on their own device.

## Provider Options

Google Gemini is the recommended default because of its permanent free tier (no credit card required).

| Provider | Free Tier | Requests/Day | Notes |
|---|---|---|---|
| Google Gemini (Flash-Lite) | Yes, permanent | 1,000 | No credit card. Best default option. |
| Google Gemini (Flash) | Yes, permanent | 250 | Better quality, tighter limits |
| Groq (Llama 3.3 70B) | Yes | 1,000 | Fast inference, no credit card |
| Mistral | Yes | ~1B tokens/mo | Generous token allowance |
| OpenAI | $5 credit (expires 3mo) | varies | Not a real free tier |
| Anthropic (Claude) | No free API tier | — | Paid only |

At Gemini Flash-Lite's free tier, a user transforming 100 posts/day uses 10% of their daily quota. Normal social media usage fits comfortably within the free limits.

## UX Considerations

### Latency
LLM calls take 500ms–1.5s per post. The feed should render raw posts immediately, then swap in transformed content with a subtle transition (shimmer → resolved). Users see content instantly; transformations arrive moments later.

### Selective Processing
Not every post needs transformation. The app should be smart about when to invoke the LLM:

- Skip posts already in the user's preferred language
- Only fact-check posts above a certain vote/engagement threshold
- Only run personality commentary on posts in specific topics
- Respect rate limits by prioritizing visible posts over prefetched ones

### Settings UI
- **API Key**: single text field, stored locally, with a "Test Connection" button
- **Transformations**: ordered list of rules. Each rule has a type (replace/amend), a prompt template, and optional filters (topic, minimum votes, language)
- **Presets**: importable/exportable JSON configs so users can share transformation setups ("Charlie Kirk preset", "Crypto analyst preset")

### Shared Presets as Social Objects
The "subscribe to Agent Charlie Kirk" social experience can still exist — not as an on-chain agent, but as a shared preset config that users import. Popular presets could be listed in a discovery page within the app. The preset is just a prompt template + filters; the actual LLM execution happens on each user's device with their own key.

## What This Replaces

The original design (from the Feb 2026 agent discussion) proposed on-chain agents that publish amendment transactions to the blockchain. That approach had several issues:

- **Composability**: agents could only operate on the root post, not on each other's output
- **Conflict resolution**: multiple agents targeting the same field required priority ordering
- **Message bloat**: every agent action added transactions to the chain
- **Amend-only agents were indistinguishable from bot replies**

The client-side approach solves all of these. Transformations compose naturally in a pipeline, there are no conflicts (it's one user's device), the blockchain stays clean, and the feature is strictly more powerful than on-chain amendments.

## Implementation Scope

This is a **frontend-only feature**. No changes needed to:
- Blockchain / node
- Backend API
- Indexer
- Shared modules

The entire feature lives in the React Native app (and web frontend if applicable). It needs:
- Secure local storage for the API key
- A generic LLM client that supports Gemini / OpenAI / Anthropic API formats
- A transformation pipeline that processes posts before rendering
- Settings UI for key entry, rule configuration, and preset management
- Visual indicators for transformed content (replace indicator + tap-to-reveal-original, amend styling)

## Open Questions

- Should presets be shareable on-chain (as a special post type) or off-chain (JSON files, URLs)?
- Rate limit strategy: queue + prioritize visible posts, or process eagerly and cache?
- Cache transformed posts locally to avoid re-processing on scroll-back?
- Should there be a "global off" toggle that instantly shows raw posts everywhere?
