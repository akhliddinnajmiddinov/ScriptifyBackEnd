FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies for psycopg2
RUN apt-get update && \
    apt-get install -y libpq-dev gcc && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Ensure migrations directories exist
RUN mkdir -p  /app/apps/user/migrations
RUN touch /app/apps/user/migrations/__init__.py

RUN mkdir -p  /app/apps/scripts/migrations
RUN touch /app/apps/scripts/migrations/__init__.py

COPY . /app/
RUN python manage.py collectstatic --noinput

# Clean up build dependencies
RUN apt-get remove -y gcc && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "scriptify_backend.wsgi:application"]