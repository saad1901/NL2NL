<div align="center">

# NL2SQL

<img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+" />
<img src="https://img.shields.io/badge/Django-6.0-092E20?style=for-the-badge&logo=django&logoColor=white" alt="Django 6.0" />
<img src="https://img.shields.io/badge/LangChain-1.3+-1C3C3C?style=for-the-badge&logo=chainlink&logoColor=white" alt="LangChain 1.3+" />
<img src="https://img.shields.io/badge/Apache_ECharts-5.4-AA344D?style=for-the-badge&logo=apache&logoColor=white" alt="Apache ECharts 5.4" />

<br />
<br />

```text
███╗   ██╗██╗     ██████╗ ███████╗ ██████╗ ██╗     
████╗  ██║██║     ╚════██╗██╔════╝██╔═══██╗██║     
██╔██╗ ██║██║      █████╔╝███████╗██║   ██║██║     
██║╚██╗██║██║     ██╔═══╝ ╚════██║██║▄▄ ██║██║     
██║ ╚████║███████╗███████╗███████║╚██████╔╝███████╗
╚═╝  ╚═══╝╚══════╝╚══════╝╚══════╝ ╚══▀▀═╝ ╚══════╝
```

### Talk to your databases in plain English

*Query any SQL database without writing a single line of SQL.*

[![Live Demo](https://img.shields.io/badge/🌐_Live_Demo-nl2nlbysaad.pythonanywhere.com-5c7cfa?style=for-the-badge)](https://nl2nlbysaad.pythonanywhere.com/)

</div>

---

## What is NL2SQL?

NL2SQL is a full-stack Django application that turns natural-language questions into executable SQL, runs the query safely, and returns results as tables, charts, and clear summaries.

That means business users can explore data with plain English instead of writing SQL by hand.

```text
“Show me the top 10 customers by revenue this quarter”
                │
                ▼
        LangChain + LLM reasoning
                │
                ▼
SELECT customer_name, SUM(revenue) AS total
FROM orders
WHERE created_at >= DATE_TRUNC('quarter', NOW())
GROUP BY customer_name
ORDER BY total DESC
LIMIT 10;
                │
                ▼
     Execute + summarise + visualise
                │
                ▼
“Acme Corp leads with $142k, followed by ...”  📊
```

---

## ✨ Features

<table>
  <tr>
    <td width="50%" valign="top">

### 🧠 Agentic Query Pipeline
- Up to 8 LLM iterations per question
- Auto-corrects SQL errors
- Runs exploratory queries for schema validation
- Handles multi-step reasoning for complex requests

### 📊 Interactive Dashboard
- AI-generated ECharts visualisations
- Supports bar, line, pie, scatter, radar, and funnel charts
- Saves charts per database
- Fullscreen, refresh, and PNG export actions

  </td>
    <td width="50%" valign="top">

### 🔌 Multi-Provider LLM Support
- Google Gemini
- OpenAI GPT models
- Anthropic Claude
- OpenRouter
- Ollama for local/offline usage

### 🗄️ Flexible Database Connections
- PostgreSQL, MySQL, SQL Server, SQLite
- CSV / Excel files auto-converted to SQLite
- Schema caching and auto-fetch
- Session-scoped credential mode

  </td>
  </tr>
  <tr>
    <td valign="top">

### 💬 Rich Chat Interface
- Streaming SSE responses with live status
- Markdown rendering for tables, code, and formatting
- Toggle SQL visibility per message
- Exportable query history

  </td>
    <td valign="top">

### ⚙️ Admin & Management
- Full Django admin integration
- Per-user database management
- Schema browser with column metadata
- Dark/light theme toggle

  </td>
  </tr>
</table>

---

## 🏗️ Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                Browser (Tailwind CSS + Vanilla JS)           │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐      │
│  │   Chat UI    │   │  Dashboard   │   │  DB Manager  │      │
│  │ (SSE stream) │   │  (ECharts)   │   │   (CRUD)     │      │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘      │
└─────────┼──────────────────┼──────────────────┼──────────────┘
          │                  │                  │
┌─────────▼──────────────────▼──────────────────▼─────────────┐
│                     Django 6 (views.py)                     │
│         ask_view | dashboard_chart_view | databases_view    │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                  aiView.py — Agentic Loop                   │
│                                                             │
│   ┌──────────┐   ┌────────────┐   ┌──────────────────────┐  │
│   │ System   │   │  LLM call  │   │     run_sql tool     │  │
│   │ Prompt + │──▶│ (iter 1-8) │──▶│    execute_query     │  │
│   │ Schema   │   │            │◀──│   feedback on error  │  │
│   └──────────┘   └────────────┘   └──────────────────────┘  │
│                         │                                   │
│                         ▼                                   │
│               Summary LLM → nl_response                     │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                 Provider Layer (app/providers/)             │
│        gemini | openai | anthropic | openrouter | ollama    │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) package manager

### Installation

```bash
git clone https://github.com/saad1901/NL2NL.git
cd NL2NL
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Open **http://127.0.0.1:8000**, register an account, and add your first database.

### Environment Variables (optional)

Copy `.Example_env` to `.env` and fill in defaults:

```env
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
GEMINI_API_KEY=your_key_here
OLLAMA_BASE_URL=http://localhost:11434
```

> LLM credentials can also be configured per-user directly in the **Settings** page, so a `.env` file is optional.

---

## 🔑 Getting a Free API Key

| Provider | Free Tier | Best For |
|---|---|---|
| [Google Gemini](https://aistudio.google.com/apikey) | 1500 req/day | Fast, reliable SQL |
| [OpenRouter](https://openrouter.ai/keys) | Multiple free models | Variety, no billing |
| [Ollama](https://ollama.com) | Unlimited (local) | Privacy, offline use |

### Recommended free OpenRouter models

```text
google/gemma-3-27b-it:free
deepseek/deepseek-chat-v3-0324:free
meta-llama/llama-3.3-70b-instruct:free
```

---

## 📁 Project Structure

```text
NL2SQL/
├── app/
│   ├── models.py
│   ├── views.py
│   ├── aiView.py
│   ├── aiTools.py
│   ├── admin.py
│   └── providers/
│       ├── gemini.py
│       ├── openai.py
│       ├── anthropic.py
│       ├── openrouter.py
│       ├── ollama.py
│       └── router.py
├── templates/
│   ├── base.html
│   ├── chat.html
│   ├── databases.html
│   └── settings.html
├── NL2SQL2/
│   ├── settings.py
│   └── urls.py
├── user_data/
├── pyproject.toml
└── .Example_env
```

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Backend | Django 6.0, Python 3.12 | Web framework, ORM, auth |
| AI Orchestration | LangChain 1.3+ | Tool-calling and agent workflows |
| LLM Providers | Gemini, OpenAI, Anthropic, OpenRouter, Ollama | SQL generation and summarisation |
| SQL Parsing | `sqlglot` | Validation and dialect normalisation |
| Frontend | Tailwind CSS, Vanilla JS | UI with no build step |
| Charts | Apache ECharts 5.4 | Interactive visualisations |
| Markdown | marked.js 12 | Response rendering |
| DB Drivers | psycopg2, pymysql, sqlite3 | Database connectivity |
| Package Manager | `uv` | Fast dependency management |

---

## 📸 Screenshots

> Chat interface with streaming responses and a result table

```text
┌─────────────────────────────────────────────────────┐
│  NL2SQL  │  Cars Dataset 1  [Dashboard]             │
├──────────┼──────────────────────────────────────────┤
│          │                                          │
│ Databases│  You: Show top 5 cars by price           │
│          │                                          │
│ Settings │  🤖 Here are the 5 most expensive...     │
│          │  ┌─────────────────────────────────┐     │
│ Docs     │  │ Brand │ Model │ Price           │     │
│          │  │ Audi  │ RS7   │ 8,900,000       │     │
│          │  │ BMW   │ X5    │ 4,950,000       │     │
│          │  └─────────────────────────────────┘     │
│          │  [View SQL] [CSV] [Copy MD]              │
└─────────────────────────────────────────────────────┘
```

---

## 🔒 Security Notes

- Database passwords are currently stored in plain text during development; encrypt them before production deployment.
- `DEBUG = True` and the default `SECRET_KEY` should both be changed before production use.
- Generated SQL is validated as `SELECT`-only before execution.
- API keys are masked in the admin panel and never exposed in model responses.

---

## 🗺️ Roadmap

- [ ] Fernet encryption for stored database credentials
- [ ] Production deployment guide with Docker + Nginx
- [ ] CSV/Excel export from chat results
- [ ] Chart PNG export from dashboard
- [ ] Query sharing or public links
- [ ] Scheduled queries and email reports
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

### Built with ☕, agents, and too many LLM API calls

</div>