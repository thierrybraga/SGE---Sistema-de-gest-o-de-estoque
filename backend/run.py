#!/usr/bin/env python3
"""
run.py — Inicialização local do servidor StockOS com Flask + SQLite

Uso:
    python run.py

Variáveis de ambiente opcionais:
    FLASK_ENV=development (padrão)
    SECRET_KEY=sua-chave-secreta
    JWT_SECRET_KEY=sua-chave-jwt

Acesso:
    http://localhost:5000
"""
import os
import sys

# Garante que o diretório de dados existe
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

from app import create_app

config_name = os.environ.get("FLASK_ENV", "development")
app = create_app(config_name)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = config_name == "development"

    print("=" * 60)
    print("  StockOS — Sistema de Controle de Estoque Enterprise")
    print("=" * 60)
    print(f"  URL:    http://localhost:{port}")
    print(f"  Env:    {config_name}")
    print(f"  DB:     SQLite (data/stock.db)")
    print("=" * 60)

    app.run(host="0.0.0.0", port=port, debug=debug)
