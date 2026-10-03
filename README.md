# Ocasionly

A personal wardrobe manager with an AI stylist. Photograph your clothes once, describe an occasion ("company dinner on Friday, it will be cold"), and the app proposes outfits built **only from garments you own**, explains the reasoning, shows the exact pieces, and renders an image of you wearing each outfit.

> **Status:** personal single-user prototype. It runs on your own machine and stores everything locally. The whole platform (interface, messages and the stylist's replies) is in English. Portuguese file and folder names are still understood by the importer.

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Bulk import](#bulk-import)
- [Privacy and cost](#privacy-and-cost)
- [Architecture](#architecture)
- [API overview](#api-overview)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)

## Features

| Area | Description |
|---|---|
| **Wardrobe** | Garments organised in tabs: T-shirts, Shirts, Hoodies/Sweaters, Shorts, Trousers, Socks, Coats, Shoes, Accessories. Thumbnail or detail view, multi-photo upload per category, and editing of every attribute (name, category, colour, size, brand, model, fit, material, season, formality, notes). |
| **Stylist** | A free-text request returns 2 to 3 outfits: the written recommendation first (why it works, how to wear it, how it should fit), then the concrete garments, then a generated image of you wearing the outfit. Each outfit can be rated, and the stylist learns from the rating. |
| **Fitting room** | Upload photos of yourself and pick up to 8 garments to see how they look on you. Generated images always have a plain, neutral background. |
| **Wishlist** | Save product links (title, image, store and price are read from the page), mark stores as *interested* or *not interested*, and ask the AI for purchase ideas based on what you already own. |
| **Memory** | The stylist does not start from scratch. It knows your height, weight and usual sizes, a free-text profile, durable facts it has learned, and your recent request history. All of it is visible and editable. |
| **Models** | A settings screen to configure each model, test it with one click, and monitor token usage. No file editing or restart required. |

## How it works

```
wardrobe photos + attributes ─► text / vision model ─► outfits (JSON) ─► garments + text in the UI
                                       ▲                                        │
   profile, measurements, memory,      │                                        ▼
   history, preferred stores ──────────┘            your photo + garment photos ─► image model ─► you in the outfit
```

1. **Wardrobe.** Each garment is a photo plus attributes. Photos are normalised (EXIF orientation, max 1280 px, JPEG) and stored on disk; square thumbnails are generated on first request.
2. **Advice.** The request is sent to the model together with a compact catalogue of the wardrobe (one line per garment), the profile, measurements, memory and recent history. With more than 24 garments, a first text-only call shortlists up to 24 relevant candidates, and only those are sent again, with downscaled photos, for the final answer. The model returns garment ids as JSON and the app renders the real garments.
3. **Fit.** The model compares each garment's size with your usual size for that category and flags pieces that will likely fit loose or tight.
4. **Learning.** Durable facts you state in a request ("I never wear brown") are stored automatically. Outfit ratings with a comment are distilled into new facts. Newly learned facts are shown after each answer and can be undone with one click.
5. **Fitting room.** The selected garment photos and your photo are sent to an image-editing model (Gemini by default), which returns the composite image. The prompt asks for a plain, seamless light-grey studio backdrop, and the result is checked: the left, right and top edges must be uniform, colourless and not dark. If they are not, one more attempt is made with a stricter instruction (so one image can cost up to two generations).
6. **Purchase ideas.** The model suggests pieces that are missing from your wardrobe, restricted to stores you marked as *interested*, together with a ready-made search link. It does not browse the web, so product links are not verified.

## Quick start

**Requirements:** macOS or Linux, [uv](https://docs.astral.sh/uv/) (`brew install uv`). Python 3.11+ is handled by `uv`.

```bash
git clone https://github.com/Joao1531/ocasionly.git
cd ocasionly
uv sync
cp .env.example .env          # optional: everything can be configured in the app
uv run uvicorn app.main:app --reload
```

Open <http://localhost:8000>. On first launch the app opens the **⚙ Models** screen, where you paste your keys and test each model.

`--reload` restarts the server automatically when the code changes. After updating the code, hard-refresh the browser (Cmd+Shift+R) if it shows a stale interface.

### Using it from a phone

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://<computer-ip>:8000` on the phone (same Wi-Fi) and use "Add to Home Screen". **The app has no authentication.** With `--host 0.0.0.0`, anyone on your network can use it and change its settings. Only expose it on networks you trust.

## Configuration

Everything can be set on the **⚙ Models** screen (stored in `data/settings.json`, readable only by you) or in `.env`. Values set in the app take precedence.

| Purpose | Variables | Notes |
|---|---|---|
| Text and vision (advice, suggestions, photo analysis) | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_VISION_MODEL` | Any OpenAI-compatible `/chat/completions` API. Defaults to **opencode Go** (`https://opencode.ai/zen/go/v1`, model `glm-5.3-flash`, which accepts images). Leave `LLM_VISION_MODEL` empty to stop the model from seeing photos. |
| Fitting room (image generation) | `GEMINI_API_KEY`, `TRYON_MODEL`, `TRYON_BASE_URL` | Requires a model with **image output** (default `gemini-2.5-flash-image`, key from <https://aistudio.google.com/apikey>). Image models may require billing. Optional: everything else works without it. |
| Import folder | `IMPORT_DIR` | Defaults to `~/Desktop/Wardrobe`. |
| Data location | `WARDROBE_DATA_DIR` | Defaults to `./data`. Useful for tests and demos. |

Each model has a test button:

- **Text** checks that the model answers and returns valid JSON, which the app relies on.
- **Vision** sends an image of a known colour and asks for the colour, which confirms that the model really accepts images.
- **Gemini key** validates the key and the model name (free). A separate **generation test** produces a real image and consumes one generation.

opencode Go requires a custom `User-Agent` and a stable `x-opencode-session` header; the app sends both. Check the terms of your plan to confirm that a personal wardrobe app is an acceptable use.

## Bulk import

Create a folder with one subfolder per category and let the app read it:

```
Wardrobe/
├── Tshirts/             Tshirt_White_Lefties_L_Wide.jpg
├── Shirts/
├── Hoodie-Sweaters/
├── Shorts/
├── Trousers/            Trousers_Denim_Levis_511_W33_L34.jpg
├── Socks/
├── Coats/
├── Shoes/               Puma_Palermo_44.jpg
├── Accessories/         Hat_NewEra_Beige.jpg
└── me.jpg               (loose images in the root: optional photos of you, for the fitting room)
```

Folder names are matched ignoring case, accents and punctuation. `Hoodie-Sweaters`, `Hoodie_Sweaters` and `Hoodies and Sweaters` are all accepted (a `/` cannot be used in a folder name). Portuguese folder names (`Camisas`, `Calças`, `Calções`, `Meias`, `Casacos`, `Sapatos`, `Acessórios`, `Camisolas`) are understood as well.

**Filename parsing.** File names are split on `_` and each part is classified by what it is, in any order: size (`M`, `44`, `W33`, `L34`), colour, fit (`Wide`, `Slim`), material (`Denim`), garment type, or known brand. Portuguese words (`Branca`, `Ganga`, `Chapéu`…) are understood too and translated to English. Whatever remains becomes brand and model. The result is only a proposal: every field stays editable in the app, together with the original file path.

| File | Result |
|---|---|
| `Trousers_Denim_Levis_511_W33_L34.jpg` | "Denim Levis 511 Trousers": Levis, model 511, material Denim, size W33 L34 |
| `Puma_Palermo_44.jpg` | "Puma Palermo Shoes": Puma, model Palermo, size 44 |
| `Tshirt_White_Lefties_L_Wide.jpg` | "White Lefties T-shirt": Lefties, white, size L, Wide fit |
| `Calças_Ganga_Levis_511_W33_L34.jpg` | same result as the first row (Portuguese names work too) |

**Duplicates are never imported.** The importer skips a file when another with the same name (ignoring case, accents, extension and folder) or the same content already exists, both within the folder and against what is already in the app. The server enforces this rule, not just the interface.

**Optional vision analysis** fills in colour, season and formality when the filename does not say. Modes: *off* (default, zero tokens), *only garments without a colour in the name*, or *all*. The app shows the estimated number of calls beforehand and the real token usage afterwards.

Supported formats: JPEG, PNG, WebP and HEIC (iPhone). Importing only works from the computer itself (`localhost`) and only for folders inside your home directory.

## Upgrading from the Portuguese versions

Earlier versions stored their vocabulary in Portuguese (categories such as `camisa` or `calças`, seasons such as `primavera/verão`, formality, memory kinds, colours, materials). On the first start after upgrading, the app migrates that **controlled vocabulary** to English automatically, once:

- A consistent backup of the database is written first, to `data/wardrobe.pre-english-backup.db` (if that file already exists it is kept and a timestamped one is written instead).
- Only categories, seasons, formality, memory kinds, colours and materials are converted (for example `azul-marinho` becomes `navy blue`).
- Free text you or the model wrote (garment names, notes, memory facts, history) is **never** modified.
- The migration is idempotent: running it again changes nothing.

## Privacy and cost

- **Local by default.** The database, photos, thumbnails and settings live in `data/`, which is **excluded from Git**. So are `.env` and every image file.
- **What leaves your machine.** Garment photos and attributes go to the text/vision provider (opencode by default). Your photo and the selected garment photos go to the image provider (Google by default) when you generate an image. Wishlist links are fetched by the server, which only accepts public addresses.
- **Token usage.** The catalogue is sent in a compact one-line-per-garment format, photos are downscaled (384 px for analysis, 400 px for advice) and large wardrobes are shortlisted before any photo is sent. Every answer reports how many garments were analysed and how many tokens were used, and the **⚙ Models** screen shows the total since the server started.

## Architecture

```
app/
├── main.py          API and routes: garments, advice, fitting room, static files
├── ai.py            model calls: photo analysis, two-stage advice, suggestions, learning
├── memory.py        measurements, memory, history and feedback
├── wishlist.py      links, stores and purchase ideas
├── importer.py      bulk import from a folder
├── filenames.py     filename parser
├── vocab.py         controlled vocabulary (colours, materials, categories) and the Portuguese-to-English mapping
├── scrape.py        product-link reader (public addresses only)
├── tryon.py         image model client (fitting room)
├── settings.py      settings and model tests
├── diagnostics.py   text, vision and fitting-room tests
├── config.py        settings resolution (UI over .env)
├── db.py            SQLite schema, lightweight migrations and the one-time vocabulary migration
├── images.py        resizing, thumbnails, HEIC support
└── static/          interface: HTML, CSS and vanilla JS, installable as a PWA, no build step
```

**Stack:** Python, FastAPI, SQLite, Pillow, and plain JavaScript in the browser.

## API overview

All routes live under `/api`. Interactive documentation is available at `/docs` while the server is running.

| Group | Routes |
|---|---|
| Garments | `GET/POST /items`, `PUT/DELETE /items/{id}`, `POST /items/analyze`, `GET /thumb/{name}` |
| Stylist | `POST /advise`, `POST /feedback`, `GET /history` |
| Fitting room | `GET/POST /people`, `DELETE /people/{id}`, `POST /tryon` |
| Memory | `GET/PUT /body`, `GET/PUT /profile`, `GET/POST /memories`, `PUT/DELETE /memories/{id}` |
| Wishlist | `GET/POST /wishlist`, `PUT/DELETE /wishlist/{id}`, `POST /wishlist/suggest`, `GET/POST /stores`, `PUT/DELETE /stores/{id}` |
| Import | `GET /import/config`, `POST /import/scan`, `POST /import/item`, `POST /import/person` |
| Settings | `GET/PUT /settings`, `GET /settings/models`, `GET /settings/usage`, `POST /settings/test/{kind}` |

## Limitations

- Single user, no authentication.
- There is no automated test suite. Verification so far was manual and used simulated AI servers; the quality of real model output has to be judged by using the app.
- The quality of advice and of the fitting room depends on the chosen models and on photo quality. For best results, lay each garment flat on a plain surface in good light, one garment per photo. With many garments in a single image, image models tend to lose fidelity, hence the limit of 8 garments per outfit (`MAX_OUTFIT_ITEMS` in `app/config.py`).
- Purchase ideas are searches, not verified product links.
- Generated images depend on the image model and may not reproduce garments exactly. The neutral-background check is a heuristic on the image edges: a very tight crop can fail it and trigger one extra attempt.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| "Method Not Allowed", or "The server is out of date" | The running server predates the code. Stop it (Ctrl+C) and start it again with `--reload`. |
| `MissingSessionID` from opencode | The `x-opencode-session` header is missing. The app sends it when the base URL contains `opencode.ai`; check the base URL. |
| Gemini returns 401 | Invalid key. The app sends Google keys in the `x-goog-api-key` header, never as a bearer token. |
| "The model did not return valid JSON" | Switch model on the **⚙ Models** screen and run the text test again. |
| The browser shows an old interface | Hard refresh (Cmd+Shift+R). |
| Folder import is refused | Open the app on the computer itself (`localhost`), and use a folder inside your home directory. |
