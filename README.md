# 📚 Decoupled High-Throughput Library Management System

A **decoupled, enterprise-grade, high-concurrency Library Management System** engineered with a **Medallion Architecture (Landing -> Bronze -> Silver 3NF -> Gold Analytics)**, asynchronous REST API (`FastAPI` + `uvloop` + `asyncpg`), Redis caching, atomic stored procedures, and a responsive Django Web UI. 

Designed and benchmarked to handle **~1000 requests/second** on an Intel i5 13th Gen processor with 6-8 GB RAM.

---

## 🌟 Key Features & Architecture

- **Decoupled Architecture**: High-speed Async API backend (`FastAPI` on port `8000`) separated from relational databases and Django Web UI (`django_web` on port `8080`).
- **3NF Relational Database Schema**: Fully normalized tables (`categories`, `authors`, `publishers`, `books`, `borrowers`, `borrow_records`, `fine_payments`) supporting both **PostgreSQL 16** and **MySQL 8.0**.
- **Atomic Stored Procedures & Row Locking**: Race-condition-free book checkout (`sp_issue_book`) and return handling (`sp_return_book`) using `SELECT ... FOR UPDATE` row locks.
- **B-Tree Indexing & Views**: Sub-millisecond indexed lookups on ISBNs, Student IDs, Due Dates, and Gold Analytics Views.
- **Medallion Data Pipeline**: Automated ETL daemon (`pipelines/etl_medallion.py`) staging raw payloads from Landing -> Bronze audit -> Silver 3NF -> Gold KPI reporting.
- **Redis Cache**: Sub-millisecond read response caching with automatic write-driven cache invalidation.
- **Dockerized Environment**: One-command containerization for PostgreSQL, Redis, FastAPI backend, Django Web UI, and ETL worker daemon.
- **Automated Backup & Recovery**: Scripts for timestamped gzip database backups (`scripts/backup.sh`) and 1-click database restoration (`scripts/restore.sh`).

---

## 📁 Directory & Documentation Structure

```
Library-Management/
│
├── backend/                  # Asynchronous FastAPI Service & Connection Pools
│   ├── config.py             # Environment Configuration & Pool Limits
│   ├── db.py                 # Asyncpg Database Connection Pool Manager
│   ├── cache.py              # Redis Cache Manager & Invalidation Strategy
│   └── main.py               # High-Throughput REST API Endpoints
│
├── database/                 # 3NF Schema DDL, Roles & Stored Procedures
│   ├── schema_postgres.sql   # PostgreSQL 16 3NF Tables, Indexes, Views & Procedures
│   ├── schema_mysql.sql      # MySQL 8.0 3NF Tables, Indexes, Views & Procedures
│   └── init_users.sql        # Database Role-Based Access Control Setup
│
├── description/              # 📖 Complete System Documentation Folder
│   ├── semantics.md          # System Layers, Transaction Rules & Cache Semantics
│   ├── schema.md             # 3NF ERD, Table Specs & Data Dictionary
│   └── workflow.md           # End-to-End Operational Workflows & Flowcharts
│
├── pipelines/                # Data Pipelines
│   └── etl_medallion.py      # Medallion ETL Pipeline Daemon Worker
│
├── scripts/                  # DevOps, Load Testing & Operations
│   ├── backup.sh             # PostgreSQL Database Backup Script
│   ├── restore.sh            # PostgreSQL Database Restore Script
│   └── load_test.py          # High-Concurrency Benchmark Suite (~1000 RPS)
│
├── library/                  # Django Library App (Catalog & Checkout)
├── DueBooks/                 # Django DueBooks App (Location & AJAX Returns)
├── template/render/          # Responsive HTML Templates (books.html, library.html, location.html)
├── docker-compose.yml        # Docker Multi-Container Configuration
├── Dockerfile.api            # Dockerfile for FastAPI Async Backend Service
├── Dockerfile.django         # Dockerfile for Django Web UI
├── API_DOCUMENTATION.md     # 📚 Comprehensive API Endpoints & Usage Guide
├── requirements.txt          # Python Dependencies
└── README.md                 # System Guide & Startup Instructions
```

---

## 🚀 How to Start the Website & System

You can run the application using **Docker Compose (Recommended)** or directly on your **Local Machine**.

---

### Option A: Quick Start via Docker Compose (Recommended)

Ensure Docker Desktop and Docker Compose are installed and running.

#### 1. Clone & Launch Containers
```bash
git clone https://github.com/Notgamer07/Library-Management.git
cd Library-Management

# Build and start all services in detached mode
docker-compose up --build -d
```

#### 2. Verify Running Services
Check container health:
```bash
docker-compose ps
```

You will see 5 active containers running:
- **`library_db_postgres`**: PostgreSQL 16 database on port `5432`
- **`library_redis_cache`**: Redis in-memory cache on port `6379`
- **`library_api_backend`**: Async FastAPI service on port `8000`
- **`library_django_web`**: Django Web UI on port `8080`
- **`library_pipeline_worker`**: Scheduled Medallion ETL worker daemon

#### 3. Access Application Services
- **Django Web Application UI**: [http://localhost:8080/](http://localhost:8080/)
- **FastAPI Interactive API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **FastAPI Health Status**: [http://localhost:8000/health](http://localhost:8000/health)

---

### Option B: Local Machine Execution (Without Docker)

#### 1. Prerequisites
- Python 3.10+ installed
- PostgreSQL 16 (or MySQL 8.0) installed and running locally
- Redis server running locally on port `6379`

#### 2. Virtual Environment Setup
```bash
# Create and activate virtual environment
python -m venv venv

# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### 3. Initialize Database Schema
Create database `library_db` in PostgreSQL and run the schema file:
```bash
psql -U postgres -d library_db -f database/schema_postgres.sql
```

#### 4. Configure Environment Variables
Copy `.env.example` to `.env` and configure your credentials:
```bash
cp .env.example .env
```
Configure database credentials, Redis host, and Django `SECRET_KEY` in `.env`.

#### 5. Start Decoupled FastAPI Backend
Open Terminal 1:
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

#### 6. Start Django Web UI
Open Terminal 2:
```bash
python manage.py runserver 127.0.0.1:8080
```

#### 7. Visit Web Application
Open your browser and navigate to:
- Django Web UI: `http://127.0.0.1:8080/`
- Due Books Location Page: `http://127.0.0.1:8080/location/`
- Books Catalog Page: `http://127.0.0.1:8080/books/`

---

## ⚡ Concurrency Load Testing (~1000 req/sec Verification)

Run the included high-concurrency load testing suite to verify throughput under load:

```bash
# Run load benchmark with 100 concurrent workers for 5000 requests
python scripts/load_test.py --concurrency 100 --requests 5000
```

---

## 📊 Medallion Data Pipeline Execution

Run a single ETL cycle manually or launch the background ETL daemon:

```bash
# Execute a single Medallion ETL cycle (Landing -> Bronze -> Silver -> Gold)
python pipelines/etl_medallion.py --run-once

# Launch scheduled ETL daemon worker running every 90 seconds
python pipelines/etl_medallion.py --interval-seconds 90
```

---

## 💾 Automated Database Backup & Recovery

- **Backup Database**:
  ```bash
  # Windows Git Bash / Linux / Docker sidecar:
  bash scripts/backup.sh
  ```
- **Restore Database**:
  ```bash
  bash scripts/restore.sh ./backups/library_db_backup_YYYYMMDD_HHMMSS.sql.gz
  ```

---

## 👤 Author
- **Notgamer07** (GitHub: [@Notgamer07](https://github.com/Notgamer07))
