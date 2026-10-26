# CorpFlow Portal - Mock Company Application

CorpFlow Portal is a Flask-based mock enterprise web application built for the AutoWorker AI browser automation demo. It simulates a corporate financial portal and internal ERP system where an AI agent can inspect invoices, extract data, and enter records into an internal system.

## Port Configuration
The application runs on **port 5001** to avoid conflicts:
`http://localhost:5001/`

---

## Running the Application
From the repository root (`C:\Users\Asus\.gemini\antigravity\scratch\autoworker`):
```bash
python -m mock_company_app.app
# OR
python mock_company_app/app.py
```

---

## Routes & Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Dashboard with company branding and summary metrics |
| `GET` | `/invoices` | Invoices listing with interactive search and filter |
| `GET` | `/invoices/<id>` | Single invoice detail view with semantic DOM element IDs |
| `GET` | `/internal/data-entry` | Internal system data entry form (supports URL pre-fill) |
| `POST` | `/internal/data-entry` | Process and store submission into ledger |
| `GET` | `/internal/submissions` | Submissions ledger displaying all recorded entries |
| `GET` | `/api/submissions` | JSON API endpoint returning submitted records |
| `GET` | `/api/invoices` | JSON API endpoint returning invoice catalog |
| `GET` | `/api/invoices/<id>` | JSON API endpoint returning specific invoice data |

---

## Semantic Selectors for Browser Automation (Playwright)

### Invoices Listing (`/invoices`)
- `#invoice-search-input` - Search bar
- `#invoice-status-filter` - Status dropdown filter (`ALL`, `PENDING`, `PAID`, `OVERDUE`)
- `#invoice-table` - Invoices table
- `#invoice-row-{id}` - Individual invoice row (e.g., `#invoice-row-1`)
- `#invoice-view-btn-{id}` - Link to view invoice details (e.g., `#invoice-view-btn-1`)

### Invoice Detail (`/invoices/<id>`)
- `#invoice-id` - Invoice numeric ID
- `#invoice-company` - Company name
- `#invoice-number` - Invoice number (e.g., `INV-2026-001`)
- `#invoice-amount` - Total amount
- `#invoice-currency` - Currency (`USD`, `INR`)
- `#invoice-due-date` - Payment due date
- `#invoice-status` - Status badge (`Pending`, `Paid`, `Overdue`)
- `#invoice-description` - Scope of work description
- `#copy-to-internal-btn` - Direct link transferring data to internal data entry form

### Data Entry Form (`/internal/data-entry`)
- `#data-entry-form` - Form element
- `#company_name` - Company Name input (`name="company_name"`)
- `#invoice_number` - Invoice Number input (`name="invoice_number"`)
- `#amount` - Amount input (`name="amount"`)
- `#currency` - Currency selector (`name="currency"`)
- `#due_date` - Due date picker (`name="due_date"`)
- `#notes` - Notes textarea (`name="notes"`)
- `#submit-btn` - Submit button (`type="submit"`)
- `#reset-btn` - Form reset button

### Success Confirmation (`POST /internal/data-entry`)
- `#success-message` - Success alert header
- `#submitted-id` - Generated record ID (e.g., `SUB-1001`)
- `#submitted-company-name` - Submitted company name
- `#submitted-invoice-number` - Submitted invoice number
- `#submitted-amount` - Submitted amount
- `#submitted-due-date` - Submitted due date
- `#submitted-notes` - Submitted notes
- `#submitted-timestamp` - Timestamp of record creation
- `#view-submissions-btn` - Button navigating to submissions log

### Submissions Log (`/internal/submissions`)
- `#submissions-table` - Submissions ledger table
- `#submission-row-{id}` - Row for submission record
- `#view-api-btn` - Link to `/api/submissions`

---

## Data Storage
- Invoices: `mock_company_app/data/invoices.json` (10 realistic records, mix of USD and INR)
- Submissions: `mock_company_app/data/submissions.json` (automatically persisted across requests)
