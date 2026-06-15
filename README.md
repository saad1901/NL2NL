<div align="center">

<img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
<img src="https://img.shields.io/badge/Django-6.0-092E20?style=for-the-badge&logo=django&logoColor=white"/>
<img src="https://img.shields.io/badge/LangChain-1.3+-1C3C3C?style=for-the-badge&logo=chainlink&logoColor=white"/>
<img src="https://img.shields.io/badge/Apache_ECharts-5.4-AA344D?style=for-the-badge&logo=apache&logoColor=white"/>

<br/><br/>

```
  _   _ _     ____  ____   ___  _
 | \ | | |   |___ \/ ___| / _ \| |
 |  \| | |     __) \___ \| | | | |
 | |\  | |___ / __/ ___) | |_| | |___
 |_| \_|_____|_____|____/ \__\_\_____|
```

### **Talk to your databases in plain English**
*Query any SQL database without writing a single line of SQL*

<br/>

[![Live Demo](https://img.shields.io/badge/🌐_Live_Demo-nl2nlbysaad.pythonanywhere.com-5c7cfa?style=for-the-badge)](https://nl2nlbysaad.pythonanywhere.com/)

</div>

---

## What is NL2SQL?

NL2SQL is a full-stack Django application that bridges the gap between business users and their data. Type a question in plain English — the system writes the SQL, runs it, and hands back a clean answer with tables, charts, and a natural-language summary.

No SQL knowledge required. No waiting for an analyst.

```
"Show me the top 10 customers by revenue this quarter"
        ↓  LangChain + LLM  ↓
SELECT customer_name, SUM(revenue) AS total
FROM orders
WHERE created_at >= DATE_TRUNC('quarter', NOW())
GROUP BY customer_name
ORDER BY total DESC LIMIT 10;
        ↓  Execute + Summarise  ↓
"Acme Corp leads with $142k, followed by ..."  📊
```

---

## ✨ Features

<table>
<tr>
<td width="50%">

**🧠 Agentic Query Pipeline**
- Up to 8 LLM iterations per question
- Self-corrects on SQL errors automatically
- Exploratory queries to verify schema names
- Multi-step reasoning for complex questions

**📊 Interactive Dashboard**
- AI-generated ECharts visualisations
- Bar, line, pie, scatter, radar, funnel charts
- Persistent charts saved per database
- Expand to fullscreen, refresh, export PNG

</td>
<td width="50%">

**🔌 Multi-Provider LLM Support**
- Google Gemini (free tier)
- OpenAI GPT models
- Anthropic Claude
- OpenRouter (50+ free models)
- Ollama (fully local / offline)

**🗄️ Flexible Database Connections**
- PostgreSQL, MySQL, SQL Server, SQLite
- CSV / Excel → auto-converted to SQLite
- Schema auto-fetch and caching
- Label-only mode (credentials per session)

</td>
</tr>
<tr>
<td>

**💬 Rich Chat Interface**
- Streaming SSE responses with live status
- Markdown rendering (tables, bold, code)
- Toggle SQL visibility per message
- Full query history with export

</td>
<td>

**⚙️ Admin & Management**
- Full Django admin with query viewer
- Per-user database management
- Schema browser with column types
- Dark/light theme toggle

</td>
</tr>
</table>

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Browser (Tailwind + Vanilla JS)      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Chat UI     │  │  Dashboard   │  │  DB Manager  │  │
│  │  (SSE stream)│  │  (ECharts)   │  │  (CRUD)      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
└─────────┼─────────────────┼─────────────────┼───────────┘
          │                 │                 │
┌─────────▼─────────────────▼─────────────────▼───────────┐
│                    Django 6  (views.py)                   │
│         ask_view │ dashboard_chart_view │ databases_view  │
└─────────────────────┬───────────────────────────────────-┘
                      │
┌─────────────────────▼────────────────────────────────────┐
│               aiView.py  —  Agentic Loop                  │
│                                                           │
│   ┌──────────┐    ┌───────────┐    ┌───────────────┐    │
│   │ System   │    │  LLM call │    │  run_sql tool │    │
│   │ Prompt + │───▶│ (iter 1-8)│───▶│  execute_query│    │
│   │ Schema   │    │           │◀───│  → feed back  │    │
│   └──────────┘    └───────────┘    └───────────────┘    │
│                     ↓ text reply                          │
│                   Summary LLM → nl_response               │
└──────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────────────┐
│               Provider Layer  (app/providers/)            │
│   gemini │ openai │ anthropic │ openrouter │ ollama       │
└──────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) package manager

### Installation

```bash
# Clone
git clone https://github.com/saad1901/NL2NL.git
cd NL2NL

# Install dependencies & run migrations
uv run python manage.py migrate

# Create an admin account
uv run python manage.py createsuperuser

# Start the dev server
uv run python manage.py runserver
```

Open **http://127.0.0.1:8000** — register an account and add your first database.

### Environment Variables (optional)

Copy `.Example_env` to `.env` and fill in defaults:

```env
# Fallback LLM if no model configured in UI
LLM_PROVIDER=gemini          # gemini | openai | anthropic | openrouter | ollama
LLM_MODEL=gemini-2.0-flash
GEMINI_API_KEY=your_key_here

# Ollama (local)
OLLAMA_BASE_URL=http://localhost:11434
```

> LLM credentials can also be configured per-user directly in the **Settings** page — no `.env` needed.

---

## 🔑 Getting a Free API Key

| Provider | Free Tier | Best For |
|---|---|---|
| [Google Gemini](https://aistudio.google.com/apikey) | 1500 req/day | Fast, reliable SQL |
| [OpenRouter](https://openrouter.ai/keys) | Multiple free models | Variety, no billing |
| [Ollama](https://ollama.com) | Unlimited (local) | Privacy, offline use |

**Recommended free models on OpenRouter:**
```
google/gemma-3-27b-it:free
deepseek/deepseek-chat-v3-0324:free
meta-llama/llama-3.3-70b-instruct:free
```

---

## 📁 Project Structure

```
NL2SQL/
├── app/
│   ├── models.py          # DatabaseConnection, QueryHistory, LLMProvider, DashboardChart
│   ├── views.py           # All HTTP views + SSE streaming endpoint
│   ├── aiView.py          # Agentic LLM pipeline (run_nl_query, run_chart_query)
│   ├── aiTools.py         # Schema fetch, query execution, DB drivers
│   ├── admin.py           # Full Django admin with query viewer
│   └── providers/
│       ├── gemini.py      # Google Gemini
│       ├── openai.py      # OpenAI
│       ├── anthropic.py   # Anthropic Claude
│       ├── openrouter.py  # OpenRouter
│       ├── ollama.py      # Ollama (local)
│       └── router.py      # .env-based provider selector
├── templates/
│   ├── base.html          # Tailwind config, theme toggle, Add DB modal
│   ├── chat.html          # Main chat + dashboard panel (1400+ lines)
│   ├── databases.html     # DB management with schema viewer
│   └── settings.html      # LLM provider & model configuration
├── NL2SQL2/
│   ├── settings.py
│   └── urls.py
├── user_data/             # Per-user SQLite files (CSV/Excel uploads)
├── pyproject.toml
└── .Example_env
```

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend** | Django 6.0, Python 3.12 | Web framework, ORM, auth |
| **AI Orchestration** | LangChain 1.3+ | Tool-calling, multi-step agents |
| **LLM Providers** | Gemini, OpenAI, Anthropic, OpenRouter, Ollama | SQL generation & summarisation |
| **SQL Parsing** | `sqlglot` | Validation, dialect normalisation |
| **Frontend** | Tailwind CSS (CDN), Vanilla JS | UI, no build step |
| **Charts** | Apache ECharts 5.4 | Interactive visualisations |
| **Markdown** | marked.js 12 | Rendering LLM responses |
| **DB Drivers** | psycopg2, pymysql, sqlite3 | PostgreSQL, MySQL, SQLite |
| **Package Manager** | `uv` | Fast Python dependency management |

---

## 📸 Screenshots

> Chat interface with streaming responses and result table

```
┌─────────────────────────────────────────────────────┐
│  NL2SQL  │  Cars Dataset 1  [Dashboard]             │
├──────────┼──────────────────────────────────────────┤
│          │                                          │
│  Databases│  You: Show top 5 cars by price          │
│           │                                         │
│  Settings │  🤖 Here are the 5 most expensive...   │
│           │  ┌─────────────────────────────────┐    │
│  Docs     │  │ Brand  │ Model    │ Price       │    │
│           │  │ Audi   │ RS7      │ 8,900,000   │    │
│           │  │ BMW    │ X5       │ 4,950,000   │    │
│           │  └─────────────────────────────────┘    │
│           │  [View SQL] [CSV] [Copy MD]              │
└─────────────────────────────────────────────────────┘
```

---

## 🔒 Security Notes

- Database passwords are stored plain-text in development — encrypt with Fernet before any production deployment
- `DEBUG = True` and `SECRET_KEY` is the Django default — change both for production
- All generated SQL is validated as `SELECT`-only before execution — no write operations possible
- API keys are masked in the admin panel and never exposed in responses

---

## 🗺️ Roadmap

- [ ] Fernet encryption for stored database credentials
- [ ] Production deployment guide (Docker + Nginx)
- [ ] CSV/Excel export from chat results
- [ ] Chart PNG export from dashboard
- [ ] Query sharing / public links
- [ ] Scheduled queries & email reports
- [ ] Multi-tenant SaaS mode

---

## 👤 Author

<div align="center">

**Shaikh Saad**

[![GitHub](https://img.shields.io/badge/GitHub-saad1901-181717?style=for-the-badge&logo=github)](https://github.com/saad1901)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-saad99-0A66C2?style=for-the-badge&logo=linkedin)](https://linkedin.com/in/saad99)
[![Demo](https://img.shields.io/badge/Live_Demo-pythonanywhere-1f8ef1?style=for-the-badge&logo=python)](https://nl2nlbysaad.pythonanywhere.com/)

</div>

---

<div align="center">

*Built with ☕ and too many LLM API calls*

</div>
