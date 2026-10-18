FROM docker.io/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Primero solo las dependencias (leídas de pyproject.toml): esta capa queda en caché
# mientras no cambie pyproject.toml, aunque cambie el código.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requisitos.txt \
    && pip install -r /tmp/requisitos.txt \
    && rm /tmp/requisitos.txt

COPY . .
# Instalación editable sin volver a resolver dependencias: el código queda en /app,
# junto a migrations/, data/seed/, las plantillas y los estáticos.
RUN pip install --no-deps -e . \
    && useradd --create-home --uid 1000 app \
    && chown -R app:app /app

USER app
EXPOSE 8000

# Aplica las migraciones pendientes y levanta la web.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
