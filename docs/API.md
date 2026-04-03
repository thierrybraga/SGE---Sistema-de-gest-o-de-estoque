# StockOS — API Reference

**Base URL:** `http://localhost:5000/api`
**Auth:** `Authorization: Bearer <token>` (JWT) on all protected routes.
**Body:** JSON unless noted as multipart.

---

## Roles & Permissions

| Role | Description |
|------|-------------|
| `admin` | Full access. User management, system configuration. |
| `manager` | Products, suppliers, projects, users (not admin). |
| `operator` | Movements, tool checkouts, read access. |
| `buyer` | Invoices, quotation pricing, supplier read. |

Hierarchy: **admin > manager > operator > buyer**

---

## Authentication `/api/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/login` | — | Authenticate and get JWT |
| POST | `/register` | admin, manager | Create new user |
| GET | `/me` | all | Current user profile |
| PUT | `/me` | all | Update own profile / password |
| GET | `/users` | admin, manager | List all users |
| GET | `/users/:id` | admin, manager | Get single user |
| PUT | `/users/:id` | admin, manager | Update user |
| POST | `/users/:id/deactivate` | admin, manager | Deactivate user |
| POST | `/users/:id/activate` | admin, manager | Reactivate user |
| GET | `/roles` | admin, manager | List available roles |
| GET | `/users/:id/activity` | admin, manager | User audit activity |
| POST | `/logout` | all | Logout (client-side) |

### POST /login
```json
// Request
{ "email": "admin@stock.com", "password": "admin123" }

// Response 200
{ "access_token": "eyJ...", "user": { "id": "...", "name": "...", "role": "admin", "email": "..." } }
```
Errors: `400` missing fields · `401` invalid credentials

### POST /register
```json
// Request
{ "name": "Maria", "email": "maria@x.com", "password": "min8chars", "role": "operator" }
// Response 201: user object
```
Errors: `400` weak password · `403` insufficient role · `409` email taken

---

## Products `/api/products`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | all | List products |
| POST | `/` | admin, manager | Create product |
| GET | `/:id` | all | Get product |
| PUT | `/:id` | admin, manager | Update product |
| DELETE | `/:id` | admin | Delete product |
| GET | `/low-stock` | all | Products below min_stock |
| GET | `/categories/` | all | List categories |
| POST | `/categories/` | admin, manager | Create category |
| PUT | `/categories/:id` | admin, manager | Update category |
| DELETE | `/categories/:id` | admin | Delete category |

### GET / — Query params
| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Search name/sku/barcode |
| `category_id` | uuid | Filter by category |
| `active` | 0\|1 | Filter by active status |

### POST /
```json
{
  "name": "Cimento CP II 50kg",
  "sku": "CEM-001",
  "barcode": "789...",
  "category_id": "uuid",
  "cost_price": 28.5,
  "sale_price": 39.0,
  "stock": 100,
  "min_stock": 20,
  "unit": "saco",
  "description": "..."
}
```
Errors: `409` duplicate SKU/barcode

---

## Movements `/api/movements`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | all | List movements |
| POST | `/entry` | admin, manager, operator | Stock entry |
| POST | `/exit` | admin, manager, operator | Stock exit |
| POST | `/adjustment` | admin, manager | Stock adjustment |

### GET / — Query params: `product_id`, `type`, `project_id`, `supplier_id`, `date_from`, `date_to`, `limit`

### POST /entry · /exit
```json
{
  "product_id": "uuid",
  "quantity": 50,
  "unit_cost": 5.0,
  "invoice_number": "NF-001",
  "supplier_id": "uuid",
  "project_id": "uuid",
  "observation": "..."
}
```
POST /exit error: `400` if quantity > current stock

### POST /adjustment
```json
{ "product_id": "uuid", "quantity": 130, "observation": "Inventário físico" }
```
Sets absolute stock level.

---

## Projects `/api/projects`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | all | List projects |
| POST | `/` | admin, manager | Create project |
| GET | `/:id` | all | Get project |
| PUT | `/:id` | admin, manager | Update project |
| GET | `/:id/needs` | all | List project needs |
| POST | `/:id/needs` | admin, manager | Add need |
| PUT | `/:id/needs/:need_id` | admin, manager | Update need |
| DELETE | `/:id/needs/:need_id` | admin, manager | Remove need |
| POST | `/:id/match` | admin, manager | Run stock match |

### POST /match
Reserves available stock against pending needs.
```json
// Response 200
{
  "results": [
    { "product_name": "Cimento", "needed": 200, "reserved": 150, "missing": 50, "status": "partial" }
  ]
}
```

---

## Suppliers `/api/suppliers`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | admin, manager, buyer | List suppliers |
| POST | `/` | admin, manager | Create supplier |
| GET | `/:id` | all | Get supplier |
| PUT | `/:id` | admin, manager, buyer | Update supplier |
| POST | `/:id/deactivate` | admin, manager | Deactivate |
| POST | `/:id/activate` | admin, manager | Reactivate |
| GET | `/:id/summary` | all | Full supplier profile + stats |
| POST | `/product-link` | admin, manager | Link product to supplier |
| PUT | `/product-link/:link_id` | admin, manager | Update link |
| DELETE | `/product-link/:link_id` | admin, manager | Remove link |
| GET | `/product/:product_id` | all | Suppliers for a product |
| GET | `/quotations/` | all | List quotations |
| POST | `/quotations/` | admin, manager | Create quotation |
| POST | `/quotations/:id/approve` | admin, manager | Approve quotation |
| POST | `/quotations/:id/cancel` | admin, manager | Cancel quotation |
| POST | `/quotations/:id/add-supplier` | admin, manager | Add supplier to quotation |
| PUT | `/quotation-items/:id` | admin, manager, buyer | Update item price |

### POST / (create supplier)
```json
{
  "name": "Construforte Ltda",
  "cnpj": "12.345.678/0001-90",
  "email": "...", "phone": "...", "address": "...",
  "contact_name": "...", "rating": 5.0, "avg_lead_time": 7
}
```
Errors: `400` invalid CNPJ · `409` duplicate CNPJ

### GET /:id/summary response
```json
{
  "supplier": { ... },
  "stats": { "total_invoices": 5, "total_invoices_value": 12000.0, "total_movements": 8, "open_quotations": 1 },
  "linked_products": [...],
  "invoices": [...],
  "movements": [...],
  "quotations": [...]
}
```

---

## Invoices `/api/invoices`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | admin, manager, buyer | List invoices |
| GET | `/:id` | admin, manager, buyer | Get invoice with items |
| GET | `/:id/pdf` | admin, manager, buyer | Download PDF (base64) |
| POST | `/:id/link-supplier` | admin, manager, buyer | Link supplier to invoice |
| POST | `/import-xml` | admin, manager, buyer | Import NF-e XML |
| POST | `/import-pdf` | admin, manager, buyer | Import PDF (OCR) |
| POST | `/:id/process` | admin, manager | Process: create movements |
| POST | `/:id/reverse` | admin | Reverse processed invoice |

### GET / — Query params
| Param | Description |
|-------|-------------|
| `status` | pending · processed · reversed |
| `supplier_id` | Filter by supplier UUID |
| `supplier_cnpj` | Filter by CNPJ (any format) |
| `invoice_number` | Partial match |
| `date_from` · `date_to` | ISO date range |

### POST /import-xml
Multipart form with `file` (XML NF-e). Returns invoice + parsed items + auto-match results.

### POST /:id/process
```json
// Optional item_mappings to link items to products
{
  "item_mappings": [{ "item_id": "uuid", "product_id": "uuid" }]
}
```

---

## Tools `/api/tools`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | all | List tools |
| POST | `/` | admin, manager, operator | Create tool |
| GET | `/:id` | all | Get tool detail |
| PUT | `/:id` | all (limited) | Update tool |
| POST | `/:id/deactivate` | admin, manager | Deactivate tool |
| GET | `/:id/photo` | all | Get tool photo |
| GET | `/categories` | all | Distinct categories |
| POST | `/import-csv` | admin, manager | Bulk import from CSV |
| GET | `/checkouts/` | all | List checkouts |
| POST | `/checkouts/` | admin, manager, operator | Create checkout |
| GET | `/checkouts/:id` | all | Checkout detail |
| POST | `/checkouts/:id/return` | admin, manager, operator | Record return |
| POST | `/checkouts/:id/renew` | admin, manager, operator | Extend due date |
| GET | `/report/summary` | all | Dashboard stats |
| GET | `/report/by-operator` | admin, manager | Per-operator summary |
| GET | `/report/operator/:id` | admin, manager | Operator detail |

### GET / — Query params: `active` (0|1), `category`, `condition`, `q` (text search)

### POST / (create tool)
```json
{
  "name": "Furadeira Bosch",
  "brand": "Bosch",
  "sku": "FUR-001",
  "category": "Elétrico",
  "description": "...",
  "invoice_id": "uuid",
  "invoice_number": "NF-001",
  "unit_value": 350.0,
  "total_units": 5,
  "min_units": 1,
  "condition": "new",
  "photo_base64": "data:image/jpeg;base64,..."
}
```

### POST /import-csv — Supported columns
Portuguese or English headers accepted:
`nome/name`, `marca/brand`, `sku`, `categoria/category`, `descricao/description`,
`valor_unitario/unit_value`, `total_units/total_unidades`, `min_units/unidades_minimas`, `condicao/condition`

```
// Response 201
{ "created": 5, "errors": [], "tools": [...] }
```

### POST /checkouts/ (create checkout)
```json
{
  "operator_id": "uuid",
  "expected_return_date": "2024-04-01",
  "project_id": "uuid",
  "observation": "...",
  "checkout_photo": "base64...",
  "items": [
    { "tool_id": "uuid", "quantity": 2 }
  ]
}
```
Error: `400` insufficient available units.

### POST /checkouts/:id/return
```json
{
  "items": [
    {
      "item_id": "checkout_item_uuid",
      "returned_quantity": 1,
      "condition_on_return": "good|regular|poor|maintenance",
      "observation": "..."
    }
  ],
  "return_photo": "base64...",
  "observation": "..."
}
```
Note: `tool_id` may be used instead of `item_id` as lookup key.

### POST /checkouts/:id/renew
```json
{ "new_return_date": "YYYY-MM-DD", "reason": "..." }
```

### GET /report/summary response
```json
{
  "total_tools": 12,
  "total_units": 48,
  "available_units": 35,
  "units_in_use": 13,
  "total_value": 15200.0,
  "value_in_use": 4100.0,
  "active_checkouts": 3,
  "overdue_checkouts": 1,
  "critical_tools": 2,
  "missing_tools": 0,
  "critical_list": [...],
  "overdue_list": [...]
}
```

---

## Dashboard `/api/dashboard`

All roles.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/summary` | Counts: products, stock value, alerts, projects |
| GET | `/low-stock` | Products at or below min_stock |
| GET | `/recent-movements` | Last 10 movements |
| GET | `/pending-needs` | Project needs with status=pending |

---

## Audit `/api/audit`

**Roles:** admin, manager

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List audit log entries |
| GET | `/summary` | Aggregated counts by action/entity |
| GET | `/entity/:type/:id` | Full history for a specific record |

### GET / — Query params: `user_id`, `action`, `entity_type`, `date_from`, `date_to`, `limit`, `offset`

---

## Error Reference

All errors return: `{ "error": "message" }`

| Code | Meaning |
|------|---------|
| 400 | Bad request / validation failure |
| 401 | Missing or invalid JWT token |
| 403 | Insufficient role for this action |
| 404 | Resource not found |
| 409 | Conflict (duplicate key, constraint) |
| 500 | Internal server error |

---

## Frontend Pages

| URL | Template | Description |
|-----|----------|-------------|
| `/` · `/login` | login.html | Login page |
| `/dashboard` | dashboard.html | Dashboard |
| `/products` | products.html | Product catalog |
| `/movements` | movements.html | Stock movements |
| `/projects` | projects.html | Project management |
| `/suppliers` | suppliers.html | Suppliers & quotations |
| `/invoices` | invoices.html | NF-e management |
| `/tools` | tools.html | Tool inventory & checkouts |
| `/users` | users.html | User management (admin) |
| `/reports` | reports.html | Reports & analytics |
