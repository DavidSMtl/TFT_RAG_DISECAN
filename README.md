# DiSeCan Agéntic RAG 🏛️🤖

Advanced Retrieval-Augmented Generation (RAG) system tailored for the **Parliamentary Corpus of the Canary Islands**. This project implements an **Agentic RAG pipeline** that combines local LLMs, vector search, and custom mathematical SQL logic to achieve high precision in legislation-heavy environments.

![Agentic RAG Flow](docs/agentic_rag_flow.md) *(Click to see the detailed Mermaid diagram)*

---

## 🚀 Key Innovations

### 1. Agentic Query Transformer
The system doesn't just "search words". It uses a **Query Analyzer LLM** to route user intent into three distinct channels:
- **Semantic Concepts**: General ideas expanded with lemmas and synonyms.
- **Literal Terms**: Quotes or specific words that must match exactly (ignoring lemmatization).
- **Sequential Phrases**: Parliamentary N-grams (e.g., *"Proposición no de ley"*) protected from stop-word filtering.

### 2. Mathematical Sequential Search (Positional SQL)
To solve the "stop-word blind spot", we implemented a custom SQL engine in `db.py` that checks for the **mathematical adjacency** of words using the `posElementoFrase` column. This allows finding specific legal phrases even if they consist mostly of common words.

### 3. Hybrid RRF Fusion
Combines **ChromaDB (Semantic)** and **MySQL (Lexical)** results using **Reciprocal Rank Fusion (RRF)**, ensuring the most relevant documents appear first regardless of the search method.

---

## 🛠️ Prerequisites

- **Python 3.11+**
- [**uv**](https://github.com/astral-sh/uv) (Fast Python package manager)
- **Ollama** (Running locally for Qwen 3B/7B models)
- **Docker & Docker Compose** (For MySQL database)

---

## ⚙️ Setup Guide

### 1. Environment Configuration
Create a `.env` file in the root directory:
```env
# Database
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=disecan
DB_USER=root
DB_PASS=your_password

# Models
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_BASE_URL=http://localhost:11434
```

### 2. Infrastructure
Launch the MySQL database container:
```bash
docker compose up -d
```
*Note: The first run will import the database dump located in `database/init/` (if provided).*

### 3. Dependencies
Install the Python environment:
```bash
uv sync
```

### 4. Vector Ingestion
Once the MySQL database is ready, generate the vector embeddings in ChromaDB:
```bash
uv run python src/backend/ingestion.py
```
*Tip: Embeddings are forced to **CPU** by default to prevent VRAM crashes while Ollama is running.*

---

## 🖥️ Usage

### Start the Backend Server
```bash
uv run python src/main.py
```

### Access the Web Interface
Open your browser at: **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## 📂 Project Structure

- `src/backend/`: Core logic (Orchestrator, Retrievers, SQL Logic).
- `src/frontend/`: Responsive UI (HTML/JS/CSS).
- `database/`: SQL scripts for initial setup and sampling.
- `docs/`: Documentation and architecture diagrams.

## 🧪 Utilities

- **`database/create_sample.py`**: Extract a small SQL sample from a large DB for local dev.
- **`src/backend/lemmatizer.py`**: Interface with the external lemmatization service.

---

## ⚠️ Important Notes
- **Local Execution**: This project is designed to be 100% local. Ensure Ollama is running before starting the server.
- **Hardware**: For optimal performance (Reranking + Synthesis), at least 16GB RAM and a decent GPU (8GB+ VRAM) are recommended, though it can run on CPU.
