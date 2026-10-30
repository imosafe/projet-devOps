FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/appuser/.local/bin:$PATH"
WORKDIR /app
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser
COPY --chown=appuser:appuser requirements.txt . 
RUN pip install --require-hashes --no-cache-dir --user -r requirements.txt
COPY --chown=appuser:appuser . .
EXPOSE 5000
CMD ["uvicorn" ,"app:app", "--host" ,"0.0.0.0","--port" ,"5000"]


