FROM python:3

WORKDIR /home/bot/ 

COPY requirements.txt ./

RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY . .

CMD [ "python", "./src/main.py" ]

