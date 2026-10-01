CREATE INDEX audit_events_source_lookup_idx
  ON audit.audit_events (source_system, source_stream, source_record_id, occurred_at);
