FROM python:3

WORKDIR /home/bot/

RUN pip install uv

COPY pyproject.toml ./

RUN uv pip install --system .

RUN mkdir ./data

COPY . .

RUN python -m sqlite3 database.db < db_init.sql

CMD ["python", "main.py"]
