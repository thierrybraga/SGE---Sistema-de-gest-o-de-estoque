# StockOS — Sistema de Controle de Estoque Enterprise

Sistema web corporativo completo com suporte a multi-usuário, importação de NF-e, match por projeto, fornecedores e cotações.

## 🚀 Início Rápido (Local - SQLite)

```bash
cd backend
pip install -r requirements.txt
python run.py
```

Acesse: **http://localhost:5000**  
Login: `admin@stock.com` / `admin123`

---

## 🐳 Docker

```bash
# Sobe API + banco SQLite
docker-compose up --build api

# Com Nginx (produção)
docker-compose --profile production up --build
```

Acesse: **http://localhost:5000** (ou http://localhost com Nginx)

---

## 📁 Estrutura

```
stock-system/
├── backend/
│   ├── app/
│   │   ├── models/       ← SQLAlchemy ORM
│   │   ├── services/     ← Regras de negócio
│   │   ├── routes/       ← Controllers REST
│   │   ├── templates/    ← HTML Jinja2
│   │   └── static/       ← CSS, JS
│   ├── run.py            ← Inicialização local
│   ├── Dockerfile
│   └── requirements.txt
├── docs/
│   ├── API.md            ← Documentação da API
│   ├── ARCHITECTURE.md   ← Arquitetura e roadmap
│   └── DATABASE.sql      ← Script SQL de referência
├── docker/
│   └── nginx.conf
└── docker-compose.yml
```

---

## ✅ Funcionalidades

| Módulo | Status |
|--------|--------|
| Login / Autenticação JWT | ✅ |
| Dashboard com alertas | ✅ |
| Cadastro de produtos | ✅ |
| Entrada / Saída / Ajuste | ✅ |
| Importação NF-e XML (SEFAZ) | ✅ |
| Projetos e necessidades | ✅ |
| Engine de match estoque × projeto | ✅ |
| Gestão de fornecedores | ✅ |
| Cotações por produto | ✅ |
| Gestão de usuários | ✅ |
| Alertas de estoque mínimo | ✅ |

---

## 🔒 Perfis de Acesso

| Perfil | Permissões |
|--------|-----------|
| admin | Total |
| manager | Aprovações + relatórios |
| operator | Movimentações + produtos |
| buyer | Cotações + fornecedores |

---

## 📄 Documentação

- [API REST](docs/API.md)
- [Arquitetura](docs/ARCHITECTURE.md)
- [Banco de Dados](docs/DATABASE.sql)
