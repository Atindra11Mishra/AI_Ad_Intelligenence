# AI Ad Analyzer

Lightweight app for competitor ad intelligence. It creates a brand profile from a real website, fetches competitor ads from Meta Ad Library through Apify, analyzes copy and images with Groq models, persists structured intelligence in SQLite, and uses that data to power a grounded creative strategy chat.

## Stack

- Backend: FastAPI, SQLAlchemy, SQLite
- Frontend: Next.js, React, Tailwind/shadcn components
- Website scraping: Firecrawl
- Meta Ad Library scraping: Apify actor
- LLM/copy/summary analysis: Groq `llama-3.3-70b-versatile`
- Vision analysis: Groq `meta-llama/llama-4-scout-17b-16e-instruct`

## Features

- Add multiple brands and switch between them.
- Scrape a brand website and extract category, positioning, tone, audience, value props, and visual style.
- Resolve competitor Facebook pages before fetching ads.
- Fetch real image/carousel ad creatives from Meta Ad Library.
- Persist brands, competitors, ads, and AI analysis in SQLite.
- Analyze ad copy: hook, CTA, messaging angle.
- Analyze ad visuals: style, people/no people, text overlay, UGC vs produced, product visibility.
- Display creatives, copy, and structured analysis by competitor.
- Chat over brand profile plus analyzed competitor ads.

## Setup

### Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env`:

```env
GROQ_API_KEY=...
FIRECRAWL_API_KEY=...
APIFY_API_TOKEN=...
APIFY_ACTOR_ID=curious_coder/facebook-ads-library-scraper
APIFY_FACEBOOK_AD_COUNTRY=ALL
APIFY_FACEBOOK_AD_SORT_BY=most_recent
```

Run the API:

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Optional `frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Open `http://localhost:3000`.

## Data Flow

1. User enters brand name and website URL.
2. Backend scrapes the website with Firecrawl.
3. Groq extracts a structured brand profile.
4. User enters competitor names.
5. Backend resolves likely Facebook pages using Apify results and a simple confidence score.
6. Backend fetches Meta Ad Library data for selected competitor pages.
7. Raw scraped items are normalized into `Ad` records.
8. Copy and image analysis run through Groq.
9. Structured fields and summaries are saved to SQLite.
10. Chat context is built directly from the brand profile and analyzed ads.

No vector database or RAG layer is used because the challenge dataset is intentionally small: 2-3 competitors and 5-10 ads per competitor fit directly in the LLM prompt.

## UI Actions And API Endpoints

The Ads page has two main actions.

### Fetch Ads

The **Fetch Ads** button first calls:

```http
POST /competitors/resolve-pages
```

This resolves typed competitor names to likely Facebook pages. If the confidence score is low, the UI shows a picker with the top candidates.

After a page is resolved or selected, the frontend calls:

```http
POST /competitors/fetch
```

This endpoint creates or reuses a `Competitor` row, fetches ads from Apify, normalizes the scrape output, deduplicates repeated creatives, and creates `Ad` rows with raw fields such as Meta ad ID, format, image URLs, and copy text.

### Analyze All

The **Analyze All** button calls:

```http
POST /competitors/analyze/{brand_id}
```

This endpoint does not create new ads. It updates existing `Ad` rows by running copy analysis, vision analysis, and summary generation. It fills fields such as hook, CTA, angle, visual style, people/text-overlay flags, UGC vs produced, product visibility, creative category, summary, and analysis error state.

### Display Saved Ads

The Ads page reads stored data through:

```http
GET /competitors/ads/{brand_id}
```

This endpoint loads saved competitors and ads from SQLite, parses JSON text fields like `image_urls`, suppresses unusable placeholder copy, and returns the shape rendered by the UI.

## Task 2 To Task 3 Handoff

Task 2 is the competitor ad intelligence pipeline:

1. `POST /competitors/fetch` creates `Competitor` and `Ad` rows.
2. `POST /competitors/analyze/{brand_id}` updates those `Ad` rows with structured AI analysis.

Task 3 is the chat experience:

1. The chat frontend sends `brand_id`, the user's message, and in-memory chat history to `POST /chat`.
2. `backend/routers/chat.py` calls `build_context(brand_id, db)`.
3. `build_context` reads the selected `Brand`, its `Competitor` rows, and their analyzed `Ad` rows from SQLite.
4. It builds one text context with `BRAND PROFILE` first, then `COMPETITOR INTELLIGENCE`.
5. `build_chat_messages` inserts that context into the Groq system prompt before appending the user's question.

In other words, Task 3 does not rescrape or reanalyze ads. It uses the persisted output of Task 2 as model context.

## Schema Decisions

SQLite was chosen because the assignment needs persistence across refreshes, but not multi-user scale or distributed infrastructure. It keeps setup simple while still allowing structured queries.

Main tables:

- `brands`: website URL plus extracted profile fields.
- `competitors`: competitor names scoped to a brand.
- `ads`: raw ad copy, image URLs, copy analysis, visual analysis, creative category, summary, and analysis error state.

Some fields such as `image_urls` and `value_props` are stored as JSON text. That keeps the schema small and avoids unnecessary join tables for this scope. The tradeoff is weaker queryability than a fully normalized schema, but it is faster to build and clear enough for the challenge.

Example `Ad` row after fetching, before analysis:

```json
{
  "ad_id_meta": "1864106750903055",
  "format": "image",
  "image_urls": "[\"https://...\"]",
  "copy_text": "A moment of truth shared with the entire nation...",
  "copy_hook": null,
  "copy_cta": null,
  "copy_angle": null,
  "visual_style": null,
  "analysis_summary": null,
  "analysis_error": null
}
```

The same row after analysis:

```json
{
  "ad_id_meta": "1864106750903055",
  "format": "image",
  "image_urls": "[\"https://...\"]",
  "copy_text": "A moment of truth shared with the entire nation...",
  "copy_hook": "A nationally televised moment of truth",
  "copy_cta": "",
  "copy_angle": "social proof and emotional advocacy",
  "visual_style": "broadcast video clip",
  "has_people": true,
  "has_text_overlay": true,
  "ugc_vs_produced": "produced",
  "product_visibility": "none",
  "creative_category": "broadcast video clip_social proof and emotional advocacy",
  "analysis_summary": "Two-sentence strategy summary...",
  "analysis_error": null
}
```

The row is updated in place; analysis does not create a second ad record.

## Service Layer Responsibilities

Routes own HTTP validation, database reads/writes, and response shaping. Services own reusable external API and normalization logic.

- `services.apify`: builds Facebook Ad Library URLs, runs the Apify actor, resolves page candidates, scores page confidence, normalizes raw actor output, extracts copy/image URLs, and creates creative signatures for dedupe.
- `services.analyzer`: calls Groq for copy and vision analysis, validates JSON responses, and handles retry/backoff behavior.
- `services.text_quality`: removes scraper placeholder or unusable copy before analysis, display, and chat context construction.

This keeps route files focused on application flow while isolating third-party API behavior in service modules.

## Ad Data Normalization

The Apify actor can return noisy fields. The backend now:

- treats template placeholders like `{{product.brand}}` as missing copy,
- falls back to snapshot text when available,
- extracts copy and image URLs from Apify `snapshot.cards` carousel structures,
- keeps one best image per carousel card instead of saving both original and resized duplicates,
- deduplicates creatives by cleaned copy plus canonical image URL path, not only by Meta ad ID,
- skips video preview URLs and page profile pictures,
- prefers non-thumbnail image URLs before `s60x60`/`p64x64` assets,
- requests image media and `most_recent` sorting from the Apify actor,
- exposes placeholder-copy ads to chat as visual-only evidence.

This prevents chat from treating scraper placeholders as real competitor strategy.

## Model Choices

`llama-3.3-70b-versatile` is used for copy analysis, summaries, brand extraction, and chat because it handles structured JSON tasks and strategy language well.

`meta-llama/llama-4-scout-17b-16e-instruct` is used for image analysis because the older Groq vision model originally used by the project was decommissioned. The app includes rate-limit backoff and slower sequential analysis to avoid Groq on-demand RPM/TPM limits.

## Chat Context Preparation

The chat system prompt includes:

- brand category, tone, audience, and value props,
- competitor names and ad counts,
- ad ID, format, cleaned copy, hook, CTA, angle,
- visual style, people/text-overlay flags, UGC vs produced, product visibility,
- creative category and summary.

For ads where copy was unavailable from the scraper, copy-derived fields are suppressed and the prompt explicitly tells the model to use only visual fields.

Chat history is currently stored only in frontend React state and sent with each `/chat` request. It is not persisted in SQLite. Refreshing the page clears the chat. Persistent chat sessions would require separate chat session/message tables.

## Current Demo Data

The local SQLite demo currently has:

- Brand: `boat`
- Competitors: `JBL`, `Skullcandy`, `Mivi`
- Total ads: 24
- Analyzed ads: 24

Mivi returned 4 usable image ads through the scraper, which is slightly below the 5-10 target but more relevant than the previous Spotify demo data. JBL and Skullcandy each have 10.

## Tests

Run backend tests:

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest tests.test_backend_data_flow tests.test_apify_normalization -v
```

What they cover:

- chat context includes real competitor ad evidence,
- analysis flow sends known copy and the best image URL to model functions,
- Apify input requests most recent image ads,
- Apify card-style carousel creatives are normalized into copy and image URLs,
- duplicate image URLs and repeated creative rows are removed during normalization,
- placeholder copy is treated as missing,
- video/profile assets are not treated as image ad creatives.

## Publishing Notes

Before publishing, initialize or use a single Git repository at the project root. This workspace currently contains a nested `.git` directory inside `frontend/` from the Next.js scaffold; for a clean public submission, remove or ignore that nested repo and commit the full project from the root.

Do not commit:

- `backend/.env`
- `backend/ads_intelligence.db`
- `backend/venv/`
- `.venv/`
- `frontend/node_modules/`
- `frontend/.next/`

Use `backend/.env.example` as the safe template for required environment variables.

## Demo Walkthrough

Use `LOOM_SCRIPT.md` as the 5-10 minute recording guide. It covers the challenge objective, data flow, schema decisions, model choices, analysis pipeline, chat grounding, tradeoffs, tests, and future improvements.

## Evaluation Notes

Use `EVALUATION_NOTES.md` for a direct mapping to the challenge rubric: ad analysis and structuring, visual understanding, architectural reasoning, chat quality, problem breakdown, and tradeoffs.

## Known Limitations

- Meta Ad Library scraping is dependent on the third-party actor output shape and availability.
- Broad competitor names can resolve to the wrong Facebook page, so the app includes page resolution/confirmation.
- Some competitors may return fewer than 5 image/carousel ads.
- There is no background job queue; analysis is intentionally synchronous and paced to respect rate limits.
- Existing placeholder-copy rows can still exist in the database, but API and chat responses now suppress them.

## What I Would Improve Next

- Add a competitor replacement/delete action in the UI.
- Add live progress updates while analysis runs.
- Add an evaluation script for chat groundedness and scrape quality.
