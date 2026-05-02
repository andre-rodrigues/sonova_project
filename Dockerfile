FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config/ config/
COPY data/ data/
COPY queries/ queries/
COPY tests/ tests/

RUN mkdir -p output/bronze/successfactors \
             output/bronze/servicenow \
             output/bronze/atoss \
             output/silver/restricted \
             output/silver/internal \
             output/gold \
             output/quarantine \
             audit

CMD ["python", "-m", "src.pipeline"]
