FROM 74ls86/keysersoze:prepare

COPY . /workspace
WORKDIR /workspace
RUN pip install --exists-action=w -r requirements.txt
ENV KEYSERSOZE_DB_DIR=/workspace

CMD ["python", "app.py"]
