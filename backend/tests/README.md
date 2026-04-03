# StockOS — QA Test Suite

## Structure

```
backend/
├── tests/
│   ├── conftest.py              # Shared pytest fixtures & helpers
│   ├── run_all.py               # Master test runner (colored output)
│   ├── README.md                # This file
│   │
│   ├── unit/                    # Per-module unit tests
│   │   ├── test_auth.py         # Authentication & user management
│   │   ├── test_products.py     # Products & categories
│   │   ├── test_movements.py    # Stock movements
│   │   ├── test_projects.py     # Projects & needs
│   │   ├── test_suppliers.py    # Suppliers, links & quotations
│   │   ├── test_invoices.py     # NF-e invoice lifecycle
│   │   ├── test_tools.py        # Tool inventory & checkouts
│   │   └── test_dashboard.py    # Dashboard & audit logs
│   │
│   ├── integration/             # Cross-module workflows & DB
│   │   ├── test_db_schema.py    # Schema validation (tables, columns, indexes)
│   │   └── test_workflows.py    # End-to-end business flows
│   │
│   └── frontend/                # Template & asset tests
│       └── test_templates.py    # Page rendering smoke tests
│
├── pytest.ini                   # pytest configuration
└── docs/
    └── API.md                   # Full API endpoint reference
```

---

## Running Tests

### Install dependencies
```bash
pip install pytest --break-system-packages
# (from backend/)
pip install -r requirements.txt --break-system-packages
```

### Run all suites
```bash
# From backend/
python tests/run_all.py

# Or directly with pytest
python -m pytest tests/
```

### Run specific suite
```bash
python tests/run_all.py unit
python tests/run_all.py integration
python tests/run_all.py frontend
```

### Options
```bash
python tests/run_all.py -v    # verbose (show test names)
python tests/run_all.py -x    # stop on first failure
python tests/run_all.py unit -v -x
```

### Run a single test file
```bash
python -m pytest tests/unit/test_tools.py -v
python -m pytest tests/integration/test_db_schema.py -v
```

### Run a single test class or function
```bash
python -m pytest tests/unit/test_tools.py::TestCheckout -v
python -m pytest tests/unit/test_auth.py::TestLogin::test_login_success -v
```

---

## Test Types

### Unit Tests (`tests/unit/`)
Test individual API endpoints in isolation using a fresh in-memory SQLite database.
Each test class covers a logical resource group (CRUD, role restrictions, validation).

| File | Coverage |
|------|----------|
| `test_auth.py` | Login, register, /me, user CRUD, roles, deactivate/activate |
| `test_products.py` | Product & category CRUD, low-stock, duplicate SKU |
| `test_movements.py` | Entry, exit, adjustment, stock floor guard |
| `test_projects.py` | Project CRUD, needs CRUD, stock match |
| `test_suppliers.py` | Supplier CRUD, CNPJ validation, product links, quotation lifecycle |
| `test_invoices.py` | XML import, supplier link, process, role access |
| `test_tools.py` | Tool CRUD, CSV import, checkout/return/renew lifecycle, reports |
| `test_dashboard.py` | Dashboard endpoints, audit log access |

### Integration Tests (`tests/integration/`)
Test cross-module flows and database-level constraints.

| File | Coverage |
|------|----------|
| `test_db_schema.py` | All 17 tables exist with correct columns; all 34 indexes present; constraints (UNIQUE, CHECK) work |
| `test_workflows.py` | Purchase cycle (product→supplier→quotation→approve→movement); Tool checkout→renew→return; Invoice import→link→process; Role hierarchy boundary |

### Frontend Tests (`tests/frontend/`)
Smoke-test that every page route returns HTTP 200 without server errors, and that unauthenticated requests are correctly rejected.

| File | Coverage |
|------|----------|
| `test_templates.py` | 9 protected pages render; unauthenticated gets 302/401; static assets served |

---

## Key Conventions

### Fixtures (conftest.py)
- `app` — session-scoped Flask app with in-memory SQLite
- `client` — Flask test client
- `tokens` — dict with `{admin, manager, operator, buyer}` JWT tokens
- `auth(token)` — returns `{"Authorization": "Bearer <token>"}`
- `get/post/put/delete(client, path, token, body?)` — convenience wrappers

### DB Isolation
All tests run against an in-memory SQLite database that is created fresh per test session. No test modifies the production database.

### Environment
```
FLASK_ENV=testing → uses TestingConfig → DATABASE=":memory:" (shared URI)
```

---

## Adding New Tests

1. Create `tests/unit/test_<module>.py`
2. Import helpers: `from tests.conftest import get, post, put, delete`
3. Use `client` and `tokens` fixtures (pytest injects them automatically)
4. Follow the `class Test<Feature>` / `def test_<behaviour>` naming

Example:
```python
from tests.conftest import get, post

class TestMyFeature:
    def test_create(self, client, tokens):
        r = post(client, "/api/my-endpoint/", tokens["admin"],
                 {"name": "Test"})
        assert r.status_code == 201
        assert r.get_json()["name"] == "Test"
```

---

## Coverage Summary

| Category | Tests | Endpoints Covered |
|----------|-------|-------------------|
| Auth | 16 | 11 endpoints |
| Products | 11 | 9 endpoints |
| Movements | 8 | 4 endpoints |
| Projects | 10 | 9 endpoints |
| Suppliers | 16 | 14 endpoints |
| Invoices | 11 | 8 endpoints |
| Tools | 30 | 14 endpoints |
| Dashboard/Audit | 12 | 7 endpoints |
| DB Schema | 54 | 17 tables, 34 indexes |
| Workflows | 20 | 4 cross-module flows |
| Frontend | 16 | 9 pages + 4 assets |
| **Total** | **~204** | **~90 endpoints** |
