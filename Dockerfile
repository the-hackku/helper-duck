FROM python:3

WORKDIR /home/bot/

RUN apt-get update && apt-get install -y sqlite3 && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml ./

RUN uv pip install --system .

COPY . .

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
