FROM python:3.8-slim

RUN mkdir -p /workspace

COPY . /workspace/

WORKDIR /workspace/

RUN apt-get update

RUN pip install --exists-action=w -r requirements.txt

ENV KEYSERSOZE_DB_DIR=/workspace

CMD ["python", "app.py"]