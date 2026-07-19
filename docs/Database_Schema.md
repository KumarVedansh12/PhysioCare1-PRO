# PhysioCare data model

The application uses Supabase PostgreSQL exclusively. Connection credentials are supplied through `DATABASE_URL`; SSL is required and there is no embedded database fallback.

The portal uses Django's authenticated `User` as the identity record. A user can be linked to a `PatientProfile` or `DoctorProfile`.

Core relationships:

- Patient → appointments, treatment plans, exercise assignments, progress entries
- Patient → prescriptions, medical records, payments, feedback
- Doctor → appointments, treatment plans, prescriptions, exercise assignments
- User → notifications, sent chat messages, received chat messages
- Appointment → optional payment/invoice

Files use Django storage fields so production storage can be switched from the local `media/` directory to Cloudinary or S3 without changing the domain model.
