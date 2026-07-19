# API extension guide

The browser experience is currently server-rendered for speed, accessibility, and simple deployment. Django REST Framework and SimpleJWT are included in the production dependency set so the same models can expose authenticated mobile or third-party APIs.

Recommended endpoint groups:

- `/api/auth/` — JWT sign-in, refresh, email OTP
- `/api/patients/me/` — profile and medical history
- `/api/appointments/` — list, book, reschedule, cancel
- `/api/treatment-plans/` and `/api/exercises/`
- `/api/records/` and `/api/prescriptions/`
- `/api/messages/` and `/api/consultations/`
- `/api/notifications/`
- `/api/payments/` and `/api/invoices/`
- `/api/doctor/` and `/api/admin/` role-protected resources

Use object permissions so patients can only access their own records, doctors can access assigned patients, and administrators receive explicit role-based permissions.
