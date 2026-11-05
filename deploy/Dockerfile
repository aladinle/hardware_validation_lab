FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY web /app/web
COPY contracts /app/contracts
RUN useradd --uid 10001 --create-home lab && mkdir -p /app/.local && chown lab:lab /app/.local
USER lab
EXPOSE 8765
CMD ["python", "web/manage.py", "runserver", "0.0.0.0:8765", "--noreload", "--insecure"]
