# CityLockers Audit

Central audit, error, and activity-correlation foundation for CityLockers systems.

It records observability data outside Supabase and must never block normal production operations. PostgreSQL is the initial central store. Kiosk integration and AI analysis are deliberately deferred.

Run locally:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The skeleton exposes `GET /health`.
