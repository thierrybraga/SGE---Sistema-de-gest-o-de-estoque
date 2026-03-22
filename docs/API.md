# StockOS — API Documentation

Base URL: `http://localhost:5000/api`

All protected routes require: `Authorization: Bearer <token>`

---

## Auth

### POST /auth/login
Login e obtenção do JWT token.

**Body:**
```json
{ "email": "admin@stock.com", "password": "admin123" }
```
**Response:** `{ "access_token": "...", "user": { ... } }`

### POST /auth/register `[Admin]`
Cria novo usuário.

**Body:** `{ "name", "email", "password", "role" }`

### GET /auth/me
Retorna usuário autenticado.

### GET /auth/users `[Admin]`
Lista todos os usuários ativos.

### PUT /auth/users/:id `[Admin]`
Atualiza usuário.

---

## Products

### GET /products/
Lista produtos. Query params: `search`, `category_id`, `active_only`

### POST /products/
Cria produto.
```json
{
  "name": "Cabo HDMI 2m",
  "sku": "CAB-HDMI-2M",
  "cost_price": 15.00,
  "sale_price": 29.90,
  "stock": 50,
  "min_stock": 10,
  "unit": "un"
}
```

### GET /products/:id
Retorna produto por ID.

### PUT /products/:id
Atualiza produto.

### DELETE /products/:id
Inativa produto (soft delete).

### GET /products/low-stock
Retorna produtos com estoque ≤ estoque mínimo.

### GET /products/categories/
Lista categorias.

### POST /products/categories/
Cria categoria.

---

## Movements

### GET /movements/
Lista movimentações. Query params: `product_id`, `type`, `project_id`, `limit`

### POST /movements/entry
Registra entrada de estoque.
```json
{
  "product_id": "uuid",
  "quantity": 10,
  "unit_cost": 15.00,
  "invoice_number": "NF-12345",
  "observation": "Compra de reposição"
}
```

### POST /movements/exit
Registra saída de estoque.
```json
{
  "product_id": "uuid",
  "quantity": 5,
  "project_id": "uuid",
  "observation": "Uso em projeto X"
}
```

### POST /movements/adjustment
Ajuste manual (requer observação).
```json
{
  "product_id": "uuid",
  "quantity": 45,
  "observation": "Correção após inventário físico"
}
```

---

## Projects

### GET /projects/
Lista projetos. Query param: `status`

### POST /projects/
Cria projeto.

### PUT /projects/:id
Atualiza projeto.

### GET /projects/:id/needs
Lista necessidades do projeto.

### POST /projects/:id/needs
Adiciona necessidade ao projeto.
```json
{
  "product_id": "uuid",
  "quantity_needed": 20
}
```

### POST /projects/:id/match
**Engine de Match** — Verifica disponibilidade e reserva estoque automaticamente.

**Response:**
```json
{
  "results": [
    {
      "product_name": "Cabo HDMI",
      "needed": 20,
      "reserved": 15,
      "missing": 5,
      "status": "partial"
    }
  ]
}
```

---

## Suppliers

### GET /suppliers/
Lista fornecedores.

### POST /suppliers/
Cria fornecedor.

### PUT /suppliers/:id
Atualiza fornecedor.

### POST /suppliers/product-link
Vincula fornecedor a produto.
```json
{
  "product_id": "uuid",
  "supplier_id": "uuid",
  "avg_price": 14.50,
  "lead_time": 5,
  "priority": 1
}
```

### GET /suppliers/product/:product_id
Lista fornecedores de um produto.

### GET /suppliers/quotations/
Lista cotações.

### POST /suppliers/quotations/
Cria cotação (adiciona fornecedores vinculados automaticamente).

### POST /suppliers/quotations/:id/approve
Aprova cotação selecionando fornecedor.

### PUT /suppliers/quotation-items/:id
Atualiza item de cotação (preço recebido).

---

## Invoices (NF-e)

### GET /invoices/
Lista notas fiscais.

### POST /invoices/import-xml
Importa XML de NF-e. Multipart/form-data com campo `file`.

**Ou JSON:**
```json
{ "xml_content": "<?xml version..." }
```

### GET /invoices/:id
Retorna nota com itens.

### POST /invoices/:id/process
Processa nota — mapeia itens para produtos e registra entradas.
```json
{
  "item_mappings": [
    { "item_id": "uuid-item", "product_id": "uuid-produto" }
  ]
}
```

---

## Dashboard

### GET /dashboard/summary
Resumo executivo: totais, alertas, movimentações recentes.

### GET /dashboard/low-stock
Produtos com estoque crítico.

### GET /dashboard/recent-movements
Últimas 10 movimentações.

### GET /dashboard/pending-needs
Necessidades de projetos pendentes.

---

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 500 | Server Error |

---

## Roles

| Role | Permissões |
|------|-----------|
| admin | Acesso total + gestão de usuários |
| manager | Aprovação de cotações, visualização de relatórios |
| operator | Movimentações, produtos |
| buyer | Cotações, fornecedores |
