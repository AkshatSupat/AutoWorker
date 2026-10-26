# AutoWorker: Autonomous AI Task Worker & Company Operator
> **CentrAlign AI — AI Engineering Intern Role Hiring Submission**  
> *Autonomous task execution, browser automation, human-in-the-loop compliance, and outcome verification.*

---

## 🌟 Executive Summary

**AutoWorker** is an autonomous AI employee runtime built to bridge the gap between high-level human objectives and end-to-end task execution across corporate digital environments. 

Rather than functioning as a passive conversational chatbot, AutoWorker autonomously:
1. **Understands** unstated business context from natural language prompts.
2. **Plans** a structured, multi-step sequence of actions using registered browser and system tools.
3. **Executes** real browser actions (navigation, DOM inspection, data extraction, form population, transaction submission) via Playwright.
4. **Observes** element states, captures screenshot evidence, and adapts when page states change.
5. **Enforces Human-in-the-Loop Safeguards** when compliance policies or monetary thresholds are triggered (e.g., invoices $\ge \$10,000$ or overdue status).
6. **Verifies** whether the user's objective was truly satisfied by collecting verifiable ledger confirmation proofs (SUB-IDs) and cross-referencing audit logs.

```
Goal ──► Understand ──► Plan ──► Execute ──► Observe ──► Adapt ──► Verify ──► Complete
```

---

## 🚀 Quick Start (Run in 2 Steps)

### 1. Prerequisites
- **Python 3.9+** (Tested on Python 3.9 - 3.12)
- Playwright Chromium (`playwright install chromium`)

### 2. Launch Everything (One Command)
Run the master launcher from the project root:

```bash
# Start both CorpFlow Enterprise Mock Portal (port 5001) & AutoWorker Dashboard (port 8000)
python run.py
```

- **Dashboard UI**: `http://localhost:8000`
- **Mock Enterprise ERP Portal**: `http://localhost:5001`

### 3. Alternative CLI & Automated Test Commands
```bash
# Run CLI autonomous execution with live browser
python run.py --cli "Find the latest invoice from Acme Corp, extract the amount and due date, enter it into our internal system, and tell me once it is done."

# Run in headless mode with auto-approval
python main.py --headless --auto-approve "Find the latest invoice from TechVision Solutions, extract the amount and due date, enter it into our internal system, and tell me once it is done."

# Run full automated verification test suite
python run.py --test
# or
python test_autoworker.py
```

---

## 🏛️ System Architecture

AutoWorker is structured into modular, decoupled layers adhering to clean architectural boundaries:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Master AutoWorker Runtime                       │
│                        (Goal-Driven Controller)                        │
└───────┬──────────────┬──────────────┬──────────────┬─────────────┬─────┘
        │              │              │              │             │
        ▼              ▼              ▼              ▼             ▼
┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐
│  Planner     ││  Executor    ││  Observer    ││  Verifier    ││ Human-Loop   │
│  Dual-Engine ││  Safe Tool   ││  Multimodal  ││  Audit Proof ││ Interactive  │
│  Gemini 2.0  ││  Invoker +   ││  DOM & Entity││  Validation  ││ Web + CLI    │
│  + Heuristic ││  Context Sub ││  Extraction  ││  Ledger Audit││ Approvals    │
└──────────────┘└──────────────┘└──────────────┘└──────────────┘└──────────────┘
        ▲              │              │              │             ▲
        │              ▼              ▼              │             │
        │       ┌──────────────┬──────────────┐      │             │
        │       │ Browser Tool │  File Tool   │      │             │
        │       │ (Playwright) │  (OS Storage)│      │             │
        │       └──────────────┴──────────────┘      │             │
        │                      │                     │             │
        └──────────────────────┼─────────────────────┘             │
                               ▼                                   │
                    ┌──────────────────────┐                       │
                    │ SQLite Memory Engine │───────────────────────┘
                    │ (Tasks/Steps/Context)│
                    └──────────────────────┘
```

### Component Breakdown

1. **Agent Runtime (`agent/runtime.py`)**  
   The core orchestrator driving the execution loop. It manages task state, coordinates step execution with configurable retries, handles re-planning upon unexpected DOM mutations, and streams events via WebSockets.

2. **Dual-Engine Planner (`agent/planner.py`)**  
   - **Primary Engine**: Google Gemini 2.0 Flash (`google-genai` SDK) utilizing structured tool definitions and context injection.
   - **Autonomous Heuristic Fallback Engine**: When API keys are absent, unauthenticated, or offline, the planner dynamically decomposes goals into deterministic browser actions so evaluators can inspect real Playwright executions without third-party key setup.

3. **Step Executor (`agent/executor.py`)**  
   Executes actions against the `ToolRegistry` with timeout safeguards (45s default). Implements dynamic variable substitution (`{company_name}`, `{amount}`, `{due_date}`) drawn from working memory.

4. **Result Observer (`agent/observer.py`)**  
   Analyzes tool outputs and screenshots. Performs semantic entity extraction (Vendor Name, Invoice ID, Due Date, Amounts, Confirmation SUB-IDs) into runtime memory and recommends next actions: `continue`, `retry`, `replan`, or `abort`.

5. **Human-in-the-Loop Guardrail (`agent/human_loop.py`)**  
   Monitors high-risk actions. If an invoice exceeds the enterprise threshold ($\ge \$10,000$ USD or Overdue status per policy), the agent pauses execution and requests explicit human sign-off via modal or CLI prompt (`[y/N]`).

6. **Outcome Verifier (`agent/verifier.py`)**  
   Independently evaluates whether the initial user goal was completed. Gathers concrete cryptographic/database evidence (ledger submission IDs, timestamped confirmations, ledger table presence) rather than assuming success from raw tool returns.

7. **Persistent State & Memory (`agent/memory.py`)**  
   SQLite-backed storage (`autoworker.db`) recording Tasks, Steps, Observations, Screenshots, Context Key-Values, and Company Knowledge Base rules.

---

## 💻 Mock Enterprise Application (CorpFlow Portal)

To realistically demonstrate cross-application workflow navigation, AutoWorker includes **CorpFlow Portal** (`http://localhost:5001`), an enterprise web application with:

| Route | Purpose | Key Semantic Selectors |
|---|---|---|
| `/invoices` | Accounts Payable Catalog | `#invoice-search-input`, `#invoice-row-{id}`, `#invoice-view-btn-{id}` |
| `/invoices/<id>` | Detailed Invoice Document | `#invoice-company`, `#invoice-number`, `#invoice-amount`, `#invoice-due-date`, `#copy-to-internal-btn` |
| `/internal/data-entry` | Internal ERP Ledger Form | `#company_name`, `#invoice_number`, `#amount`, `#currency`, `#due_date`, `#submit-btn` |
| `/internal/submissions` | Financial Audit Ledger Log | `#submissions-table`, `#submission-row-{id}`, `#view-api-btn` |

---

## 🎯 Evaluation Criteria Walkthrough

### 1. Autonomy
AutoWorker takes natural language goals such as:
> *"Find the latest invoice from Acme Corp, extract the amount and due date, enter it into our internal system, and tell me once it is done."*

It identifies the vendor, maps out the navigation sequence, parses unstated fields, evaluates approval rules, posts the transaction, and verifies the outcome without needing step-by-step human guidance.

### 2. Execution vs. Simulation
Unlike mock agents that generate text summaries, AutoWorker launches a **real Chromium browser via Playwright**, clicks interactive DOM elements, inspects real text nodes, submits actual HTTP POST requests, and persists data into the ERP database.

### 3. Reliability & Failure Recovery
- **Automatic Retries**: Failed steps are retried with exponential backoff.
- **Dynamic Re-Planning**: If a selector is missing or navigation fails, the observer detects the obstacle and the planner generates alternative remediation steps (e.g., navigating directly to the URL and populating manual form fields).
- **Tag-Aware Element Safety**: Automatically differentiates between standard inputs and `<select>` dropdowns, preventing Playwright fill exceptions.

### 4. Verification & Auditability
Before declaring a task finished, the verifier validates:
- Confirmation record identifier generated (e.g., `SUB-1001`).
- Successful HTTP 200/201 response.
- Presence of the newly recorded entry in the corporate submissions ledger table (`/internal/submissions`).

### 5. Generalization
AutoWorker generalizes across different vendors and currencies (e.g. Acme Corp in USD vs. TechVision Solutions in INR) without changing code logic.

---

## 🛠️ Technical Decisions & Tradeoffs

| Decision | Chosen Approach | Rationale & Tradeoffs |
|---|---|---|
| **Browser Engine** | Playwright (async) | Playwright provides auto-waiting, screenshot capturing, reliable locator APIs, and robust headless/headful modes over Selenium. |
| **LLM Provider** | Google Gemini 2.0 Flash (`google-genai`) | Rapid reasoning latency (<800ms) with high instruction-following accuracy for JSON schema outputs. |
| **Resilience Strategy** | Dual-Engine Architecture | Seamless fallback to deterministic heuristic planner when API keys are absent, ensuring offline operability during technical evaluations. |
| **State Persistence** | SQLite (`autoworker.db`) | Zero-configuration serverless database ensuring auditability across agent restarts without requiring PostgreSQL/Redis setup. |
| **Frontend Dashboard** | Vanilla CSS + Modular JS + WebSockets | Instant response time, real-time streaming, and zero bundle-build overhead (no Node/webpack required). |

---

## 📋 Known Limitations & Future Roadmap

### Known Limitations
1. **Dynamic CAPTCHA**: Currently assumes company portals do not require CAPTCHAs or 2FA SMS tokens.
2. **Complex Multi-Tab Navigation**: AutoWorker currently operates within a single browser context tab.
3. **Infinite Scroll Pagination**: Very deep tables (>1,000 items) require explicit pagination clicks rather than virtualized scroll listeners.

### What to Build Next (Next Iteration)
1. **Vision-Language Model (VLM) Coordinate Clicking**: Support pixel-level computer use (`mouse_click(x, y)`) for legacy enterprise desktop apps and Citrix environments.
2. **Dynamic Policy Graph Retrieval (RAG)**: Index corporate SOP PDFs and HR policies using vector embeddings (`ChromaDB` / `FAISS`) to resolve domain-specific edge cases.
3. **Session Replay Video Generation**: Auto-compile Playwright video traces into instant MP4 walkthroughs for supervisor compliance archives.

---

## 🧪 Testing AutoWorker

AutoWorker comes with an end-to-end automated test suite:

```bash
# Run tests
python -m unittest test_autoworker.py
```

Sample output:
```text
----------------------------------------------------------------------
Ran 2 tests in 16.685s

OK
```

---

## 📦 Project Directory Structure

```
autoworker/
├── agent/                  # Core AI Agent Runtime
│   ├── executor.py         # Step executor with variable substitution
│   ├── human_loop.py       # Human-in-the-loop approval & supervisor controls
│   ├── memory.py           # SQLite persistent memory engine
│   ├── observer.py         # Gemini observation & semantic entity extraction
│   ├── planner.py          # Gemini 2.0 Flash + Heuristic Dual Planner
│   ├── runtime.py          # Master orchestrator loop & event dispatcher
│   └── verifier.py         # Outcome verifier & audit proof compiler
├── config/                 # Environment & configuration settings
├── dashboard/              # Enterprise Web Dashboard (FastAPI + WebSockets)
│   ├── server.py           # REST API & WebSocket event streaming server
│   └── static/             # Frontend SPA (HTML5, Vanilla CSS, JS)
├── mock_company_app/       # CorpFlow Enterprise Portal (Port 5001)
│   ├── app.py              # Flask enterprise portal
│   ├── data/               # Invoices & submissions database
│   └── templates/          # Jinja2 templates with semantic DOM selectors
├── screenshots/            # Playwright browser captures & visual evidence
├── tools/                  # Extensible Tool Registry (Browser, Files)
├── test_autoworker.py      # Automated End-to-End Test Suite
├── run.py                  # Master One-Click Launcher
├── main.py                 # CLI Entrypoint
└── requirements.txt        # Python package dependencies
```

---

*CentrAlign AI Engineering Hiring Showcase — Autonomous AI Task Worker Submission.*
