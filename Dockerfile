FROM python:3.10-slim

WORKDIR /app

COPY . /app

RUN pip install -r PlummyScrapper/requirements.txt

EXPOSE 8080

CMD ["uvicorn", "PlummyScrapper.main:app", "--host", "0.0.0.0", "--port", "8080"]
