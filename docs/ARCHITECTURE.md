# StockOS — Arquitetura e Roadmap

## Visão Geral

Sistema de Controle de Estoque Enterprise com suporte a:
- Multi-usuário com perfis (admin, gerente, operador, compras)
- Importação de NF-e (XML SEFAZ)
- Match automático de necessidades por projeto
- Gestão de fornecedores e cotações
- API REST completa

---

## Stack Tecnológica

```
┌─────────────────────────────────────────────────┐
│  Frontend (HTML/CSS/JS + Jinja2 Templates)       │
│  ┌──────────┐ ┌────────────┐ ┌───────────────┐  │
│  │ Dashboard│ │  Produtos  │ │  Movimentações│  │
│  └──────────┘ └────────────┘ └───────────────┘  │
│  ┌──────────┐ ┌────────────┐ ┌───────────────┐  │
│  │ Projetos │ │  NF-e/XML  │ │  Fornecedores │  │
│  └──────────┘ └────────────┘ └───────────────┘  │
└───────────────────────┬─────────────────────────┘
                        │ fetch() / API REST
┌───────────────────────▼─────────────────────────┐
│  Flask API (Python 3.11)                         │
│  ┌──────────┐ ┌────────────┐ ┌───────────────┐  │
│  │  Routes  │ │  Services  │ │  Repositories │  │
│  └──────────┘ └────────────┘ └───────────────┘  │
│  Flask-JWT-Extended │ Flask-CORS │ SQLAlchemy   │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│  SQLite (local / dev) ou PostgreSQL (produção)   │
└─────────────────────────────────────────────────┘
```

---

## Padrão MVC / Layered Architecture

```
app/
├── routes/          → Controllers (HTTP handlers)
│   ├── auth.py
│   ├── products.py
│   ├── movements.py
│   ├── projects.py
│   ├── suppliers.py
│   ├── invoices.py
│   ├── dashboard.py
│   └── frontend.py
├── services/        → Business Logic (SOLID)
│   ├── auth_service.py
│   ├── product_service.py
│   ├── movement_service.py
│   ├── project_service.py
│   ├── supplier_service.py
│   ├── invoice_service.py
│   └── dashboard_service.py
├── models/          → SQLAlchemy ORM Models
│   ├── user.py
│   ├── product.py
│   ├── movement.py
│   ├── project.py
│   ├── supplier.py
│   └── invoice.py
├── core/
│   ├── config.py    → Environment configs
│   └── seed.py      → Initial data
├── templates/       → Jinja2 HTML pages
└── static/          → CSS, JS
```

---

## Princípios SOLID Aplicados

| Princípio | Implementação |
|-----------|--------------|
| **S** Single Responsibility | Cada service tem uma única responsabilidade |
| **O** Open/Closed | Novos conectores (SAP, ERP) podem ser adicionados sem modificar o core |
| **L** Liskov Substitution | Services são intercambiáveis via interfaces |
| **I** Interface Segregation | Repositories específicos por entidade |
| **D** Dependency Inversion | Services injetados nas routes via parâmetro |

---

## Modelo ER (Entidade-Relacionamento)

```
users ──────────────────────────────────────┐
  │                                          │
  ├──► movements ◄── products ◄── categories│
  │         │              │                 │
  │         │              ├──► project_needs◄── projects
  │         │              │
  │         │              ├──► product_suppliers ◄── suppliers
  │         │              │                               │
  │         └──────────────┘                               │
  │                                                         │
  └──────────────────────────► quotations ◄────────────────┘
                                    │
                              quotation_items
  
  invoices ──► invoice_items ──► products (match)
```

---

## Roadmap de Implantação

### ✅ Fase 1 — MVP (Concluído)
- [x] Autenticação JWT + perfis
- [x] CRUD completo de produtos
- [x] Entrada, saída, ajuste de estoque
- [x] Dashboard com alertas
- [x] Importação NF-e XML (parser SEFAZ)

### 🟡 Fase 2 — Projetos & Match
- [x] CRUD de projetos
- [x] Engine de match estoque × necessidade
- [x] Reserva de estoque por projeto
- [ ] Relatórios exportáveis (CSV/Excel)

### 🟠 Fase 3 — Cotações & Fornecedores
- [x] CRUD fornecedores
- [x] Vínculo produto × fornecedor
- [x] Workflow de cotação
- [ ] Envio automático de email de cotação

### 🔵 Fase 4 — Integrações
- [ ] Conector SAP (OData/RFC)
- [ ] API Gateway
- [ ] Webhooks
- [ ] Fila de mensagens (RabbitMQ)

### 🟣 Fase 5 — IA & Deep Research
- [ ] Serviço LLM para análise de cotações
- [ ] RAG interno (histórico de preços)
- [ ] Previsão de reposição
- [ ] Busca automática de fornecedores

---

## Docker

```bash
# Desenvolvimento (SQLite)
docker-compose up api

# Produção (com Nginx)
docker-compose --profile production up
```

## Uso Local

```bash
cd backend
pip install -r requirements.txt
python run.py
# http://localhost:5000
# admin@stock.com / admin123
```
