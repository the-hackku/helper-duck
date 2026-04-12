FROM python:3

WORKDIR /home/bot/

RUN pip install uv

COPY pyproject.toml ./

RUN uv pip install --system .

COPY db_init.sql ./

RUN python -m sqlite3 database.db < db_init.sql

RUN mkdir ./data

COPY . .

CMD ["python", "main.py"]
