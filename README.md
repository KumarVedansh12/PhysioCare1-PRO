# PhysioCare

PhysioCare is a patient-first physiotherapy management portal built with Django. It includes accessible patient, doctor, and clinic administration workspaces with appointments, treatment plans, exercises, progress tracking, secure messages, medical records, reminders, payments, reviews, and downloadable PDFs.

## Database: Supabase PostgreSQL only

PhysioCare has no SQLite fallback. The application will refuse to start until a valid PostgreSQL `DATABASE_URL` is configured.

1. Open your Supabase project.
2. Click **Connect** at the top of the Supabase dashboard.
3. For a persistent Django/Gunicorn server, copy the **Session pooler** URI (port `5432`). Use the direct URI when the deployment supports IPv6. Transaction pooler URIs on port `6543` are also detected and configured without prepared statements.
4. Open `.env` in this project and replace the complete `DATABASE_URL` value with the copied URI.
5. Replace `[YOUR-PASSWORD]` with the database password. If entering it manually, percent-encode special URL characters. Never commit or send this URI to anyone.

The connection is configured here:

```env
DATABASE_URL=postgresql://postgres.PROJECT_REF:YOUR_PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require
```

SSL is mandatory by default. Database health checks and persistent connections are enabled for direct/session connections. Supabase transaction-pooler connections automatically disable prepared statements and Django-side persistent connections.

## Local setup after connecting Supabase

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

Demo accounts (all use password `Care@123`):

- Patient: `patient`
- Doctor: `drmeera`
- Clinic admin: `admin`

`seed_demo` is optional and should only be used for a new demonstration database. Do not run it against a real clinic database.

## Production deployment

Copy `.env.example` into your hosting provider’s secret/environment settings and supply real values. Production defaults enforce HTTPS cookies, HSTS, trusted hosts, proxy SSL headers, restricted CORS, PostgreSQL SSL, structured console logging, and hashed static assets.

Deployment files included:

- `Dockerfile` — non-root Python application container
- `gunicorn.conf.py` — bounded workers, threads, timeouts, and request recycling
- `deploy/entrypoint.sh` — deployment checks, migrations, and static collection
- `deploy/nginx/physiocare.conf` — HTTPS proxy and static/media routing template
- `Procfile` — web and release commands for compatible platforms

Before serving real patient data, configure Cloudinary or another durable private media store, SMTP, your WhatsApp provider, error monitoring, encrypted backups, and a custom production domain.
