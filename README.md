# OmniFeed

> Autonomous Multimodal Content Pipeline for the Qoneqt Global Feed.

OmniFeed transforms any raw topic, prompt, idea, or community trend into publish-ready 9:16 vertical video packages. The pipeline pairs LLMs for scripting and 3-second retention hook engineering with visual models, neural voice synthesis (`edge-tts`), kinetic word-aligned subtitles (`libass`), and headless FFmpeg assembly.

---

## Key Features

- **3-Second Retention Hook Engine**: Evaluates three distinct candidate hooks for mobile feed attention spans and programmatically selects the highest-retention opening.
- **Context-Adaptive Scripting**: Calibrates tone, pacing (~2.5 words/second), and vocabulary to specific community subcultures across English (`en-IN`), Hindi (`hi-IN`), and Marathi (`mr-IN`).
- **Safety & Claim Verification**: Impartial automated moderation check flagging hate speech, dangerous acts, and deceptive medical or financial advice.
- **Neural Voice & Word-Boundary Timing**: Natural speech synthesis with sub-second word-boundary alignments.
- **Visuals Engine**: Prioritized visual generation pipeline (OpenAI-compatible image generation → Pixabay vertical portrait photo search → high-contrast cinematic typography cards).
- **Kinetic ASS Captions**: Word-level subtitle highlighting in the lower-middle safe zone, rendered with font support for Latin and Devanagari scripts (`Noto Sans Devanagari`, `DejaVu Sans`).
- **Headless FFmpeg Rendering**: Per-scene Ken Burns motion zoom, stream concatenation, audio multiplexing, and direct subtitle burning into H.264/AAC MP4.
- **Automated Quality Verification**: Validates 1080x1920 resolution, stream presence, duration tolerance (+/- 3s), and file size (< 100 MB).
- **Dual-Mode Qoneqt Publishing**: Supports both direct multipart API publishing and step-by-step assisted feed publishing.

---

## Tech Stack

- **Backend**: Python 3.11, FastAPI, Uvicorn, SQLite
- **Concurrency**: ThreadPoolExecutor worker queue (max 2 concurrent renders)
- **Frontend**: Plain HTML5, CSS3, and Vanilla JavaScript (no build step, 2-second polling)
- **Media Engine**: FFmpeg 4.4+ with `libass`, `libfreetype`, `libx264`, and Noto/DejaVu fonts

---

## Environment Variables

Copy `.env.example` to `.env` and configure your keys:

```ini
# ==============================================================================
# REQUIRED CONFIGURATION
# ==============================================================================
LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
LLM_API_KEY="your-llm-api-key"
LLM_MODEL="gemini-3.8-flash"
PIXABAY_API_KEY="your-pixabay-api-key"

# Optional fallback LLM model
LLM_FALLBACK_MODEL=""

# Optional Google Gemini key (used automatically if LLM_API_KEY is not set)
GEMINI_API_KEY=""

# ==============================================================================
# OPTIONAL CONFIGURATION (App starts and runs fully with these unset or empty)
# ==============================================================================
# AI Image Generation (OpenAI-compatible /images/generations, optional)
IMAGE_BASE_URL=""
IMAGE_API_KEY=""
IMAGE_MODEL="dall-e-3"

# Qoneqt Publishing (optional, enables API upload mode; default is Assisted mode)
QONEQT_API_BASE=""
QONEQT_API_TOKEN=""
QONEQT_UPLOAD_PATH="/api/v1/posts/upload"
QONEQT_FIELD_NAME="file"
QONEQT_APP_URL="https://qoneqt.com"

# Server Configuration
PORT=3000
HOST="0.0.0.0"
DATA_DIR="./data"
MAX_CONCURRENT_RENDERS=2
```

---

## Installation & Local Execution

### 1. System Requirements (Debian/Ubuntu)

Ensure FFmpeg and required font packages are installed:

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg fonts-dejavu fonts-noto-core fonts-noto-extra
```

### 2. Python Setup

```bash
# Clone the repository
git clone https://github.com/your-org/omnifeed.git
cd omnifeed

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Locally

```bash
python run.py
```

The server will start on `http://localhost:3000`. Open your browser to access the dashboard.

---

## Running the Smoke Test

The automated smoke test verifies server health, initiates a real 20-second video pipeline, monitors real measured latency across all 8 stages, and verifies that the output MP4 and JPG thumbnail are valid and pass ffprobe quality checks:

```bash
python scripts/smoke_test.py
```

---

## Docker Deployment

### Build the Docker Image

```bash
docker build -t omnifeed:latest .
```

### Run the Docker Container

```bash
docker run -d -p 3000:3000 --env-file .env -v $(pwd)/data:/app/data --name omnifeed omnifeed:latest
```

---

## Deploying on Render (Docker Service)

1. Fork or push this repository to GitHub.
2. Sign in to your [Render Dashboard](https://render.com).
3. Click **New +** → **Web Service**.
4. Select your `omnifeed` repository.
5. In the service configuration:
   - **Environment**: `Docker`
   - **Region**: Choose the closest region (e.g., Oregon, Frankfurt, Singapore)
   - **Instance Type**: Starter or Standard (at least 1 GB RAM recommended for FFmpeg)
6. Add Environment Variables under the **Environment** tab:
   - `LLM_API_KEY` (or `GEMINI_API_KEY`)
   - `LLM_BASE_URL` (if using custom endpoint)
   - `LLM_MODEL` (e.g. `gemini-3.8-flash` or `gpt-4o-mini`)
   - `PIXABAY_API_KEY`
   - `PORT`: `3000`
   - `DATA_DIR`: `/app/data`
   - *(Optional)* `IMAGE_API_KEY`, `IMAGE_BASE_URL`, `IMAGE_MODEL`, `QONEQT_API_TOKEN`, `QONEQT_API_BASE`
7. Click **Create Web Service**. Render will automatically build the Docker container and deploy the applet.

---

## Publishing to the Qoneqt Global Feed

OmniFeed supports two publishing workflows:

### 1. Assisted Mode (Default)
1. Generate your video on the dashboard.
2. Under the **Publishing** card in the job detail view, click **Download MP4**.
3. Click **Copy Caption** to grab the auto-generated caption with hashtags.
4. Click the link to open [Qoneqt](https://qoneqt.com) and upload the video to the Global Feed.
5. Paste your resulting post link into the confirmation box and click **Confirm Published**.
6. The job will permanently display a **Published** badge linked to your live post.

### 2. Direct API Mode
When `QONEQT_API_BASE`, `QONEQT_API_TOKEN`, and `QONEQT_UPLOAD_PATH` are set:
1. The **Publish via API** button appears in the job detail panel.
2. Clicking it submits a multipart POST request with the MP4 binary and caption.
3. The server captures and logs the exact HTTP response code and payload.

---

## API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/healthz` | Health check endpoint returning `{ status: "ok" }`. |
| `GET` | `/api/status` | Provider readiness, FFmpeg availability, and configuration status. |
| `POST` | `/api/status/test-llm` | Test connectivity and latency of the configured LLM endpoint. |
| `POST` | `/api/status/test-image` | Test connectivity and latency of the image provider. |
| `POST` | `/api/jobs` | Submit a single video generation job. |
| `POST` | `/api/jobs/batch` | Queue multiple video topics simultaneously. |
| `GET` | `/api/jobs` | Retrieve all jobs (supports `?status=` filter). |
| `GET` | `/api/jobs/{id}` | Retrieve complete job details, measured stage latencies, script, and quality report. |
| `POST` | `/api/jobs/{id}/retry` | Re-queue a failed or interrupted job. |
| `POST` | `/api/jobs/{id}/approve` | Creator approval override for safety-flagged content. |
| `POST` | `/api/jobs/{id}/publish` | Direct API publish to Qoneqt. |
| `POST` | `/api/jobs/{id}/confirm-published` | Record assisted manual publishing link. |
| `POST` | `/api/jobs/{id}/select-hook` | Switch to an alternative 3-second retention hook. |
| `DELETE` | `/api/jobs/{id}` | Delete a job and remove associated media files from disk. |
| `GET` | `/media/{id}/{file}` | Stream or download generated MP4, thumbnail JPG, or narration MP3. |

---

## Pipeline Execution Stages

Each video generation job transitions through 8 discrete stages with real measured latency:

1. `input`: Job accepted, validated, and persisted.
2. `llm_script`: 3 retention hooks generated, selection reason drafted, full script and 5-7 visual scenes planned.
3. `content_check`: Automated policy and misinformation audit.
4. `tts_voice`: Neural voice synthesized via `edge-tts` with word boundary timing extraction.
5. `visuals`: 1080x1920 9:16 scene frames generated or retrieved.
6. `captions`: ASS kinetic subtitle file generated with active-word accent styling.
7. `ffmpeg_render`: Headless zoompan motion, video concatenation, audio muxing, and subtitle burning.
8. `quality_check`: Automated `ffprobe` inspection verifying resolution, codecs, duration, and file size.
