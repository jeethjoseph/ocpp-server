# OCPP Server

### Local

1. Install requirements `pip install -r requirements.txt`
2. Once all the packages are installed `fastapi dev main.py`. We can expect the development server to start on port 8000.
3. Test websocket with `websocat ws://0.0.0.0:9000/ocpp/CP001 ` direct in bash
4. Test REST API through browser http://127.0.0.1:8000/api/, http://127.0.0.1:8000/api/charge-points, https://127.0.0.1:8000/api/ocpp/logs/CP001, https://127.0.0.1:8000/api/ocpp/logs

Best practice is to install and run in python virtual environment

### Deployment

Current deployment is in render.

### File structure

ocpp-server/
│
├── main.py # FastAPI app entrypoint (routes, startup)
├── models.py # SQLAlchemy ORM models
├── database.py # DB engine, session, and dependency
├── schemas.py # Pydantic models (request/response)
├── crud.py # CRUD operations for DB
├── websocket.py # OCPP WebSocket logic
├── utils.py # Utility functions (e.g., logging)
├── alembic/ # Alembic migrations folder (created by alembic init)
├── requirements.txt
├── schema.dbml
└── readme.md

### Alembic

1. Generate schema `alembic revision --autogenerate -m "fixed log schema removed connector id"`
2. Push schema `alembic upgrade head`

### Docs

1. https://docs.sqlalchemy.org/en/20/orm/session_basics.html
