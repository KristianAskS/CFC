# Bruk en offisiell Python 3.9 slim-image
FROM python:3.9-slim

# Sett arbeidskatalogen
WORKDIR /app

# Kopier og installer avhengigheter
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopier resten av kildekoden
COPY . .

# Start boten
CMD ["python", "src/main.py"]