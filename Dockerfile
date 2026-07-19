FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN addgroup --system physiocare && adduser --system --ingroup physiocare physiocare

WORKDIR /srv/physiocare

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x deploy/entrypoint.sh \
    && mkdir -p staticfiles media \
    && chown -R physiocare:physiocare /srv/physiocare

USER physiocare

EXPOSE 8000
ENTRYPOINT ["./deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]
