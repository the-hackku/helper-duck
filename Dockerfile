FROM python:3

WORKDIR /home/bot/ 

COPY requirements.txt ./

COPY db_init.sql ./

RUN python -m sqlite3 database.db < db_init.sql

RUN pip install -r requirements.txt

# RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

RUN mkdir ./data

COPY . .

CMD [ "python", "main.py" ]

