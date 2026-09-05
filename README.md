# CryptoRisk AI

CryptoRisk AI is a production-grade, full-stack intelligence platform that transforms raw cryptocurrency tickers into structured, AI-powered risk assessment reports. Built for high-frequency market participants and researchers, the application cuts through market hype by synthesizing complex uncertainty, downside risks, and actionable signals into an executive-level format.

---

## Architecture & System Design

The project uses a monorepo layout with a clear boundary between browser code and server code:

[ frontend/ browser UI ] --(HTTP / OAuth)--> [ backend/ Flask API ]
                                                 |
                                   +-------------+-------------+
                                   |                           |
                                   [ Google Gemini API ]       [ PostgreSQL ]

* **Frontend Layer:** HTML5, CSS, and browser JavaScript are isolated in `frontend/`.
* **Backend Layer:** Python 3.14 and Flask live in `backend/`, managing secure user sessions, CSRF protections, and OAuth verification via Authlib.
* **Intelligence Layer:** Integrates the Google Gemini API to analyze cryptocurrency tickers under strict data policies, filtering out real-time price hallucination in favor of rigorous risk analysis.
* **Data Layer:** Persistent relational storage managed via PostgreSQL, maintaining strict foreign-key constraints between authenticated users and their historical analysis reports.

---

## Tech Stack

| Layer | Technology |
| :--- | :--- |
| **Frontend** | HTML5, Modern CSS3, JavaScript (ES6+) |
| **Backend** | Python, Flask, Gunicorn |
| **Authentication** | Google OpenID Connect (OAuth 2.0 via Authlib) |
| **AI Engine** | Google Gemini API (`gemini-2.5-flash`) |
| **Database** | PostgreSQL, Psycopg2 |
| **Project layout** | Monorepo with separate `frontend/` and `backend/` applications |

---

## Core Features

* **Secure Authentication:** Frictionless Google OAuth login ensuring verified identity mapping and session safety.
* **Structured Risk Engine:** Generates uniform JSON schemas evaluating asset trends, risk scores, core problems solved, and exact counts of key risks, signals, and watch items.
* **Persistent User History:** Automatically serializes generated reports to a secure relational database indexed by user identification.
* **Defensive Error Handling:** Built-in mitigation for API quota exhaustion (`RESOURCE_EXHAUSTED`), malformed JSON recovery, and robust input sanitization.

---

## Project Structure

Crypto-Risk-AI/
├── frontend/
│   ├── config.js            # Backend service URL
│   ├── dashboard.html       # Static dashboard page
│   ├── index.html           # Static landing page
│   ├── script.js            # API client and UI behavior
│   └── style.css            # UI styles
├── backend/
│   ├── app.py               # Flask application and API integration
│   ├── requirements.txt     # Python runtime dependencies
│   ├── static/               # Backend-served browser assets
│   └── templates/            # Backend Jinja templates
├── render.yaml              # Render frontend, backend, and database setup
└── README.md

---

## Environment Variables

To run or deploy this project locally, configure the following environment variables in your environment or `.env` file:

SECRET_KEY=your_flask_session_secret
JWT_SECRET_KEY=your_jwt_secret
DATABASE_URL=postgresql://user:password@host:port/dbname
GEMINI_API_KEY=your_google_gemini_api_key
GOOGLE_CLIENT_ID=your_google_oauth_client_id
GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret
FRONTEND_URL=http://localhost:8080

---

## Local Development & Setup

1. **Clone the repository:**
   git clone <your-repository-url>
   cd <repository-directory>

2. **Set up the backend environment:**
   cd backend
   pip install -r requirements.txt

3. **Run the Flask backend:**
   python app.py

4. **Serve the frontend:**
   From the project root, run `python -m http.server 8080 --directory frontend`.

5. **Access the platform:**
   Navigate to `http://localhost:8080` in your browser.

## GitHub Setup

For a new GitHub repository, run these commands from the project root:

```bash
git init
git add .
git commit -m "Restructure project into frontend and backend"
git branch -M main
git remote add origin https://github.com/<github-username>/<repository-name>.git
git push -u origin main
```

Replace the remote URL with the repository you created on GitHub. Keep `.env` local; it is excluded by `.gitignore` and must not be committed.

## Render Deployment

This repository includes `render.yaml` for a Render Blueprint deployment.

1. Push the repository to GitHub.
2. In Render, choose **New > Blueprint** and select this repository.
3. Deploy the Blueprint. It creates a static frontend, Flask backend, and PostgreSQL database.
4. In the backend web service's Environment settings, add these secret values:
   - `GEMINI_API_KEY`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
5. Update `frontend/config.js` if Render assigns a different frontend or backend URL than the defaults in `render.yaml`.
6. In Google Cloud Console, add the backend callback URL to the OAuth authorized redirect URIs:
   `https://cryptorisk-ai-backend.onrender.com/auth/google/callback`

Render uses `gunicorn --chdir backend app:app --bind 0.0.0.0:$PORT` for the backend and publishes `frontend/` as a static site. The backend exposes `/api/session`, `/api/dashboard`, `/api/history/<id>/delete`, and `/api/health` for the frontend.
