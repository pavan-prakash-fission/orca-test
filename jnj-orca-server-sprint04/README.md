## 1️⃣ Install Dependencies

```bash
# Install all dependencies (runtime + dev) from pyproject.toml
poetry install
```

---

## 2️⃣ Configure Environment

1. Create a `.env` file in the project root (do not commit secrets).
2. Example `.env`:

```env
DB_URL=postgresql+asyncpg://user:password@localhost:5432/fastapi_db
DEBUG=True
```

3. The DB URL is referenced in `app/config/settings.py`:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    db_url: str = "postgresql+asyncpg://user:password@localhost:5432/fastapi_db"
    debug: bool = True

settings = Settings()
```

---

## 3️⃣ Generate Alembic Migrations

1. Create initial migration (Alembic will compare `target_metadata` with DB):

```bash
poetry run alembic revision --autogenerate -m "Initial migration"
```

2. This generates migration file under `alembic/versions/`.

---

## 4️⃣ Apply Migrations

```bash
poetry run alembic upgrade head
```

* This applies all pending migrations to the Postgres database.
* After this step, tables like `User` are created.

---

## 5️⃣ Verify Database

1. Run DB test:

```bash
pytest tests/test_db.py
```

* Ensures async connection works and DB is reachable.

2. Optional: Connect to Postgres and check tables:

```sql
\c fastapi_db
\dt
```

---

## 6️⃣ Running the App

```bash
poetry run uvicorn app.main:app --reload
```

* FastAPI will now use the async DB session for CRUD operations.
* All DB interactions go through `app/core/db.py` and SQLModel models.

---

## Guidelines
* **Do not commit real DB credentials** — use `.env`.
* **AsyncSession** is used at runtime; **sync engine** is only for Alembic.
* Import all models in `alembic/env.py` to ensure migrations include them.
* Incremental migrations: for new models, run `alembic revision --autogenerate` and `upgrade head`.
