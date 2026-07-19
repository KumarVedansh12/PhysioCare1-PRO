# PhysioCare

PhysioCare is a patient-first physiotherapy management portal built with Django. It includes accessible patient, doctor, reception, and clinic administration workspaces with appointments, treatment plans, exercises, progress tracking, secure messages, medical records, reminders, payments, reviews, and downloadable PDFs.

## Reception workspace

Staff assigned to the **Reception** group receive a dedicated front-desk dashboard instead of clinic-administrator access. It provides:

- Live daily queue with check-in, therapist hand-off, no-show, and cancellation states
- Fast patient search by name, ID, phone, or email
- New-patient registration with secure portal invitation
- Conflict-aware appointment booking and rescheduling with suggested available slots
- Automatic patient/doctor email notifications and optional invoice creation
- Pending-dues collection with payment method, receipt email, and staff audit trail
- Downloadable invoices, contact-enquiry handling, therapist workload, and daily totals

Create a real reception account from **Clinic Admin → Staff management** and choose the **Reception** role. The optional `seed_demo` command also creates `reception / Care@123` for local demonstration only.

Portal access is enforced by role rather than by Django's broad `is_staff` flag:

- **Clinic Manager** — clinic operations, people, appointments, employees, reports, and CMS
- **Reception** — front-desk workspace only
- **Billing** — payment reports and payment export only
- **Content Editor** — website CMS only
- **System Administrator** — superuser-only encrypted backups and advanced Django administration

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

## Email and notification setup

The project includes working email flows for patient registration OTP verification, password resets, contact-form enquiries, appointment booking/rescheduling/cancellation, doctor alerts, patient clinical updates, and automatic 24-hour/2-hour appointment reminders. Email deliveries are recorded in PostgreSQL with unique event keys to prevent duplicate sends.

Put your SMTP provider details in `.env`. Keep `EMAIL_ENABLED=0` while entering
the values, then change it to `1` only after all placeholders have been replaced:

```env
SITE_URL=https://your-real-domain.com
EMAIL_ENABLED=0
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=1
EMAIL_USE_SSL=0
EMAIL_HOST_USER=your-smtp-login
EMAIL_HOST_PASSWORD=your-smtp-password-or-app-password
EMAIL_TIMEOUT=15
EMAIL_MAX_ATTEMPTS=5
DEFAULT_FROM_EMAIL=PhysioCare <care@your-domain.com>
SERVER_EMAIL=PhysioCare <care@your-domain.com>
CONTACT_EMAIL=care@your-domain.com
EMAIL_REPLY_TO=care@your-domain.com
OTP_EXPIRY_MINUTES=10
OTP_RESEND_SECONDS=60
OTP_MAX_ATTEMPTS=5
REMINDER_POLL_SECONDS=60
```

Use TLS with port `587`, or SSL with port `465`; never enable both. Gmail requires a Google App Password when two-step verification is enabled—do not put your normal Google password in `.env`. Other providers such as Amazon SES, Brevo, Mailgun, Postmark, or Resend can be used through their SMTP credentials.

Enable email, restart the web and reminder processes so they reload `.env`, then
validate the configuration and send a real test message:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py send_test_email --to you@example.com
```

If `manage.py check` reports `core.E001`, one or more SMTP values is still empty
or contains a sample placeholder. Do not use `smtp.example.com`: it is only an
example and cannot deliver mail.

The reminder scheduler is a long-running worker. It must run beside the web server:

```bash
.venv/bin/python manage.py send_appointment_reminders --watch
```

`Procfile` and `docker-compose.yml` already define this worker. The reminder database records make repeated polling safe and prevent duplicate reminders.

## Local setup after connecting Supabase

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
./deploy/run-local.sh 8001
```

Open `http://127.0.0.1:8001/`. The script runs migrations, the web application, and the appointment-reminder worker together. Pass a different unused port if needed.

Alternatively, after completing `.env`, start the production-style containers with one command:

```bash
docker compose up --build
```

Then open `http://127.0.0.1:8000/` (or set `PORT` in your terminal for a different host port).

Demo accounts (all use password `Care@123`):

- Patient: `patient`
- Doctor: `drmeera`
- Clinic admin: `admin`
- Reception: `reception`

`seed_demo` is optional and should only be used for a new demonstration database. Do not run it against a real clinic database.

## Production deployment

Copy `.env.example` into your hosting provider’s secret/environment settings and supply real values. Production defaults enforce HTTPS cookies, HSTS, trusted hosts, proxy SSL headers, restricted CORS, PostgreSQL SSL, structured console logging, and hashed static assets.

Deployment files included:

- `Dockerfile` — non-root Python application container
- `gunicorn.conf.py` — bounded workers, threads, timeouts, and request recycling
- `deploy/entrypoint.sh` — deployment checks, migrations, and static collection
- `deploy/nginx/physiocare.conf` — HTTPS proxy and static/media routing template
- `Procfile` — web and release commands for compatible platforms
- `docker-compose.yml` — web and reminder worker processes using the same `.env`

Before serving real patient data, configure a durable media store, your WhatsApp provider if required, error monitoring, and a custom production domain. Medical reports and chat files are validated and delivered only through authenticated download views; the supplied Nginx configuration blocks direct `/media/` access. Email is SMTP-ready; SMS and WhatsApp still require separate provider credentials and API integration.

Set `BACKUP_ENCRYPTION_KEY` to a URL-safe base64 encoded 32-byte secret before production deployment. Encrypted backups contain both database records and private uploaded files. Validate an archive without changing anything:

```bash
python manage.py restore_clinic_backup FILE.pcbackup
```

Restore is deliberately limited to empty clinic tables and requires both `--restore` and `--confirm-empty-database`. Keep the encryption key in the deployment secret manager and in a separate secure recovery location.

Video consultation is currently marked **work in progress**. New appointment forms offer in-clinic visits only until a real secure video provider is integrated and tested.
