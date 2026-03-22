-- =============================================
-- StockOS — Script de Criação de Banco SQLite
-- =============================================
-- Este script é gerado automaticamente pelo SQLAlchemy
-- ao iniciar a aplicação. Use este arquivo como referência
-- do modelo de entidade-relacionamento (MER).

-- USUÁRIOS
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    role VARCHAR(30) DEFAULT 'operator',
    active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- CATEGORIAS
CREATE TABLE IF NOT EXISTS categories (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT
);

-- PRODUTOS
CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    sku VARCHAR(50) UNIQUE,
    barcode VARCHAR(50) UNIQUE,
    category_id VARCHAR(36) REFERENCES categories(id),
    cost_price FLOAT DEFAULT 0.0,
    sale_price FLOAT DEFAULT 0.0,
    stock INTEGER DEFAULT 0,
    reserved_stock INTEGER DEFAULT 0,
    min_stock INTEGER DEFAULT 0,
    unit VARCHAR(20) DEFAULT 'un',
    active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- PROJETOS
CREATE TABLE IF NOT EXISTS projects (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    cost_center VARCHAR(50),
    manager_id VARCHAR(36) REFERENCES users(id),
    status VARCHAR(20) DEFAULT 'active',
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- NECESSIDADES DE PROJETOS
CREATE TABLE IF NOT EXISTS project_needs (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id),
    product_id VARCHAR(36) NOT NULL REFERENCES products(id),
    quantity_needed INTEGER NOT NULL,
    quantity_reserved INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    observation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- FORNECEDORES
CREATE TABLE IF NOT EXISTS suppliers (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    cnpj VARCHAR(20) UNIQUE,
    email VARCHAR(120),
    phone VARCHAR(30),
    address TEXT,
    contact_name VARCHAR(100),
    rating FLOAT DEFAULT 5.0,
    avg_lead_time INTEGER DEFAULT 7,
    active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- PRODUTO x FORNECEDOR
CREATE TABLE IF NOT EXISTS product_suppliers (
    id VARCHAR(36) PRIMARY KEY,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id),
    supplier_id VARCHAR(36) NOT NULL REFERENCES suppliers(id),
    avg_price FLOAT DEFAULT 0.0,
    lead_time INTEGER DEFAULT 7,
    priority INTEGER DEFAULT 1,
    notes TEXT
);

-- MOVIMENTAÇÕES
CREATE TABLE IF NOT EXISTS movements (
    id VARCHAR(36) PRIMARY KEY,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id),
    type VARCHAR(20) NOT NULL,  -- entry, exit, adjustment
    quantity INTEGER NOT NULL,
    unit_cost FLOAT DEFAULT 0.0,
    user_id VARCHAR(36) REFERENCES users(id),
    project_id VARCHAR(36) REFERENCES projects(id),
    supplier_id VARCHAR(36) REFERENCES suppliers(id),
    invoice_number VARCHAR(50),
    observation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- COTAÇÕES
CREATE TABLE IF NOT EXISTS quotations (
    id VARCHAR(36) PRIMARY KEY,
    project_need_id VARCHAR(36) REFERENCES project_needs(id),
    product_id VARCHAR(36) NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'open',
    approved_supplier_id VARCHAR(36) REFERENCES suppliers(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ITENS DE COTAÇÃO
CREATE TABLE IF NOT EXISTS quotation_items (
    id VARCHAR(36) PRIMARY KEY,
    quotation_id VARCHAR(36) NOT NULL REFERENCES quotations(id),
    supplier_id VARCHAR(36) NOT NULL REFERENCES suppliers(id),
    unit_price FLOAT DEFAULT 0.0,
    lead_time INTEGER DEFAULT 7,
    notes TEXT,
    status VARCHAR(20) DEFAULT 'pending'
);

-- NOTAS FISCAIS
CREATE TABLE IF NOT EXISTS invoices (
    id VARCHAR(36) PRIMARY KEY,
    invoice_number VARCHAR(50) NOT NULL,
    supplier_cnpj VARCHAR(20),
    supplier_name VARCHAR(150),
    issue_date DATE,
    total_value FLOAT DEFAULT 0.0,
    status VARCHAR(20) DEFAULT 'pending',
    xml_content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ITENS DE NOTA FISCAL
CREATE TABLE IF NOT EXISTS invoice_items (
    id VARCHAR(36) PRIMARY KEY,
    invoice_id VARCHAR(36) NOT NULL REFERENCES invoices(id),
    product_id VARCHAR(36) REFERENCES products(id),
    description VARCHAR(200),
    ncm VARCHAR(20),
    quantity FLOAT DEFAULT 0.0,
    unit VARCHAR(10),
    unit_price FLOAT DEFAULT 0.0,
    total_price FLOAT DEFAULT 0.0,
    matched BOOLEAN DEFAULT 0
);

-- ÍNDICES
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_movements_product ON movements(product_id);
CREATE INDEX IF NOT EXISTS idx_movements_created ON movements(created_at);
CREATE INDEX IF NOT EXISTS idx_project_needs_project ON project_needs(project_id);
