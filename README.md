# AskYourData (NL2NL AI System)

AskYourData is a full-stack Django application that lets users query relational databases in plain English, automatically converts those questions into SQL, runs the SQL on the selected database, and returns both human-readable insights and interactive charts.[1]

**Live Demo:** [https://nl2nlbysaad.pythonanywhere.com/](https://nl2nlbysaad.pythonanywhere.com/)

## Overview

The project is designed for non-technical users such as managers and analysts who need answers from business data without writing SQL.[1] It also keeps the workflow transparent for technical users by supporting generated SQL visibility and preserving a full query history for audit and debugging use cases.[1]

The application uses Django as the web framework, Tailwind CSS with vanilla JavaScript for the frontend, LangChain-based AI orchestration, and `sqlglot` for SQL parsing and validation.[1] It supports PostgreSQL, MySQL, and SQLite-style workflows through configurable database connections and schema-aware prompting.[1]

## Key Features

- Ask questions in natural language and receive SQL-backed answers.[1]
- Execute generated SQL against connected databases and return formatted results.[1]
- Display structured output as tables together with plain-English summaries.[1]
- Generate interactive line, bar, and pie charts for query results.[1]
- Manage multiple database connections per user with session-based isolation.[1]
- Keep a per-database query history for traceability and debugging.[1]
- Support optional schema descriptions to improve prompt quality and accuracy.[1]

## How It Works

The application follows a schema-aware natural language to analytics pipeline.[1]

```text
User Question
   ↓
Schema Context + Connection Metadata
   ↓
LangChain / LLM Pipeline
   ↓
Generated SQL
   ↓
SQL Validation
   ↓
Database Execution
   ↓
Rows + Columns
   ↓
Natural-Language Summary + Chart Configuration
```

In practice, the system reads the target database structure, combines that schema context with the user question, generates SQL, executes it on the selected database, and formats the returned data for both tabular and visual presentation.[1] This makes the interface useful for both quick KPI checks and exploratory analytics.[1]

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6, Python 3.12+ |
| AI / LLM | LangChain, langchain-openai, langchain-community |
| SQL Safety | `sqlglot` |
| Databases | PostgreSQL, MySQL, SQLite |
| Frontend | Tailwind CSS (CDN), Vanilla JavaScript |
| Charts | Apache ECharts |
| Package Management | `uv` |
| App Storage | SQLite (`db.sqlite3`) |

All of these technologies are described in the current project context, including the use of `uv` for dependency management and the Django app database stored in SQLite for local app state.[1]

## Core Modules

### 1. Authentication and Session Handling

The platform uses Django's built-in user model and session-based authentication to protect routes and isolate each user's connected databases.[1] This enables a simple multi-database workflow without requiring JWT or separate token infrastructure.[1]

### 2. Database Connection Management

Each user can create and manage labeled database connections with metadata such as host, port, database name, SSL usage, and optional schema descriptions.[1] The `DatabaseConnection` model is responsible for storing this configuration and supports multiple connection types.[1]

### 3. Query Processing

Every natural-language question is tracked through the `QueryHistory` model, which stores the user prompt, generated SQL, natural-language response, error state, and timestamp.[1] This provides useful observability for debugging, user support, and future model improvement.[1]

### 4. Visualization Layer

The chat interface can render returned rows and columns as charts in addition to tables, using Apache ECharts integrated directly in the Django template flow.[1] The system supports line charts for temporal data, bar charts for categorical comparisons, and pie charts for composition-style summaries.[1]

## Project Structure

```text
NL2SQL2/
├── app/
│   ├── models.py
│   ├── views.py
│   ├── aiView.py
│   ├── aiTools.py
│   └── migrations/
├── templates/
│   ├── base.html
│   ├── chat.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard_empty.html
│   ├── add_database.html
│   └── databases.html
├── db.sqlite3
├── pyproject.toml
└── uv.lock
```

The current structure separates app logic, AI orchestration, and presentation templates clearly, which makes the project easier to extend and debug.[1]

## Main Workflows

### Natural Language to SQL

1. The user selects a database and enters a plain-English question.[1]
2. The system gathers schema context from the destination database.[1]
3. An LLM generates SQL tailored to the schema and database engine.[1]
4. The query is validated and executed on the selected database.[1]
5. The results are returned as rows, columns, and a natural-language explanation.[1]

### Result Presentation

1. The backend returns a structured JSON response from the `/chat/<db_id>/ask/` endpoint.[1]
2. The frontend renders the answer in the chat UI, optionally exposes the SQL, and shows result tables when row data is available.[1]
3. The same result shape can drive Apache ECharts visualizations for fast dashboard-style interpretation.[1]

## Why This Project Matters

AskYourData reduces dependency on analysts or engineers for routine business reporting by making databases accessible through plain English.[1] It is especially useful in environments where decision-makers need fast answers but do not know SQL.[1]

At the same time, the project remains developer-friendly because it preserves the generated SQL, keeps historical records, and can be extended into a stronger audited analytics workflow.[1]

## Current Status

The project context notes that the architecture and UI are in place, while some AI execution components and hardening steps are still being completed.[1] Known areas include finalizing the LLM pipeline in `aiView.py`, implementing schema utilities in `aiTools.py`, encrypting stored passwords, and wiring the database listing template to real data.[1]

This makes the repository a strong applied AI + backend systems project that already demonstrates product design, database integration, and LLM-driven analytics workflows.[1]

## Local Setup

### Prerequisites

- Python 3.12+
- `uv`
- A supported SQL database to connect to

### Installation

```bash
git clone https://github.com/saad1901/NL2NL.git
cd NL2NL
uv run python manage.py migrate
uv run python manage.py runserver
```

The project context specifies `uv run python manage.py migrate` for migrations and `uv run python manage.py runserver` for local development.[1]

## Demo Link

The application is available here: [https://nl2nlbysaad.pythonanywhere.com/](https://nl2nlbysaad.pythonanywhere.com/)

## Resume-Style Highlights

- Built a LangChain-powered system that translates natural language into SQL, executes the query, and returns formatted results.[1]
- Enabled secure multi-database workflows with Django sessions and user-scoped connection management.[1]
- Added schema lookup from `INFORMATION_SCHEMA`-style metadata to improve SQL quality and reduce hallucinations.[1]
- Integrated Apache ECharts for dynamic analytics dashboards inside a Django application.[1]

## Future Improvements

- Add encrypted storage for database passwords.[1]
- Complete and harden the AI execution pipeline in `aiView.py` and `aiTools.py`.[1]
- Replace placeholder UI elements in the databases page with fully dynamic rendering.[1]
- Add production-ready configuration for secrets, allowed hosts, and debug settings.[1]

## Author

**Shaikh Saad**  
GitHub: [saad1901](https://github.com/saad1901)  
LinkedIn: [saad99](https://linkedin.com/in/saad99)