# Wedding RSVP backend

FastAPI service with PostgreSQL persistence and a PostgreSQL-backed email outbox.
The browser frontend is intentionally not connected to this API yet.

## Requirements

- Python 3.11 or newer
- PostgreSQL 14 or newer
- A Gmail account with 2-Step Verification and an App Password for notifications

## Local setup

Run commands from the `backend` directory.

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Create a PostgreSQL database and user (run in `psql` as a database
   administrator, replacing the local password with a private value):

   ```sql
   CREATE USER wedding_rsvp_app WITH PASSWORD 'use-a-private-local-password';
   CREATE DATABASE wedding_rsvp OWNER wedding_rsvp_app;
   ```

4. Create your local configuration:

   ```powershell
   Copy-Item .env.example .env
   ```

   Edit `.env` locally. Set `DATABASE_URL` to your PostgreSQL connection string,
   set `CORS_ORIGINS` to a JSON array containing your served frontend origin,
   and provide a Gmail address, Gmail App Password, and matching `MAIL_FROM`.
   The notification recipient defaults to `bhuisompa001@gmail.com`. Never commit
   `.env` or put SMTP credentials in frontend files.

5. Apply migrations:

   ```powershell
   alembic upgrade head
   ```

6. Start the API (in one terminal):

   ```powershell
   uvicorn app.main:app --reload
   ```

7. Start the email worker (in another terminal):

   ```powershell
   python -m app.worker
   ```

The API health check is `GET http://127.0.0.1:8000/health`; interactive API
documentation is at `http://127.0.0.1:8000/docs`.

## Render deployment

The [Render Blueprint](./render.yaml) describes three separate production
resources: a managed PostgreSQL database, a FastAPI web service, and a
background worker. The API binds to `0.0.0.0` and Render's `PORT`; its `/health`
endpoint is used for health checks. The worker runs `python -m app.worker` and
shares the managed database and SMTP settings. Do not configure a disk or
SQLite database for production.

1. Push the repository to GitHub without any `.env` files or credentials. In
   Render, select **New → Blueprint**, connect the repository, and select the
   branch containing `backend/render.yaml`. Review the Blueprint and create the
   resources. The Blueprint uses paid Starter services and a Basic-256mb
   PostgreSQL instance; select suitable plans/region for your account if
   Render prompts for them.
2. In the `wedding-rsvp-api` service's environment settings, set `CORS_ORIGINS`
   to a JSON array with the exact deployed frontend origin, for example
   `["https://your-wedding-site.example"]`. Do not include a path or trailing
   slash. The frontend is not connected by this backend change.
3. In **both** `wedding-rsvp-api` and `wedding-rsvp-email-worker`, set
   `SMTP_USERNAME`, `SMTP_PASSWORD`, and `MAIL_FROM` using Render's environment
   secret fields. Use a Gmail account address, its Gmail App Password, and a
   sender address authorized for that account. The recipient is configured as
   `bhuisompa001@gmail.com`; never put email credentials in Git, this file, or
   frontend code.
4. The API Blueprint's `preDeployCommand` runs `alembic upgrade head` before
   each API deployment, using the same managed `DATABASE_URL` as the service.
   The command applies pending migrations and must complete successfully or the
   deployment is stopped. For a one-time/manual migration, use the Render
   Shell for the API service and run `alembic upgrade head` from its root
   directory (`backend/`). Do not run migrations independently from the worker.
5. Deploy and wait for the API health check to pass. Verify the service's
   `/health` endpoint and logs, then check the worker logs for
   `RSVP email worker started.`. Keep both services connected to the same
   managed database. Configure frontend CORS with only the exact production
   origin.

Render supplies `DATABASE_URL` from the managed database connection string;
the application normalizes Render's `postgres://`/`postgresql://` schemes to
the installed psycopg v3 driver. `PORT` is supplied by Render and consumed by
the API start command. SMTP credentials use Blueprint `sync: false` variables,
so they must be entered privately in the Render dashboard and are not stored
in the repository. No deployment is performed by these instructions.

## API contract

`POST /api/rsvp` accepts JSON:

```json
{
  "name": "Guest name",
  "mobile": "+15551234567",
  "guests": 2,
  "attendance": "Both Events",
  "message": "Best wishes"
}
```

`mobile` and `message` are optional. `guests` must be an integer from 1 through
20. Attendance must be one of:

- `Wedding Ceremony (13 December 2026)`
- `Reception & Dinner (14 December 2026)`
- `Both Events`
- `Unable to Attend`

The optional `Idempotency-Key` header deduplicates API retries. Reusing the key
with the same submission returns the existing RSVP; reusing it with different
data returns `409`. Multiple submissions using the same mobile number are
allowed.

New records return `201` once both the RSVP and pending email notification job
are committed. Email is delivered asynchronously by the worker. A retry of an
already accepted idempotent request returns `200` with the notification's
current outbox status. The endpoint has a
per-process, per-client-IP rate limit configured using `RATE_LIMIT_REQUESTS`
and `RATE_LIMIT_WINDOW_SECONDS`.

## Testing

From `backend`:

```powershell
python -m pytest
```

The tests use SQLite and a mocked SMTP transport; local PostgreSQL and Gmail
credentials are not required to run them.

## Outbox operations

The worker claims jobs with PostgreSQL row locks and a lease, renews the lease
while sending, and uses an unguessable per-claim token for renewal and
conditional finalization. A worker whose lease expires cannot change the job
after another worker claims it. The worker sends via Gmail SMTP STARTTLS and
retries transient failures with bounded exponential backoff. After
`OUTBOX_MAX_ATTEMPTS`, a job is marked failed for operator
review. Check application logs and query `email_outbox` to monitor delivery;
failed jobs can be retried after correcting SMTP configuration by setting
their status back to `pending` and `next_attempt_at` to the current time.
Delivery is at-least-once: if SMTP accepts a message but the worker exits before
marking its job sent, a later lease retry may send a duplicate notification.

The API and worker both require the same `.env` and database. Run Alembic
migrations before starting either process. Production should use a managed
PostgreSQL database, HTTPS, and platform secret settings for all credentials.
