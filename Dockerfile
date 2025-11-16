FROM python:3.10-slim

WORKDIR /app

COPY . /app

RUN pip install -r PlummyScrapper/requirements.txt

CMD ["python", "PlummyScrapper/plummy.py"]

EXPOSE 8080
 
