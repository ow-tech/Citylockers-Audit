CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE audit.systems (
  code text PRIMARY KEY,
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit.services (
  id uuid PRIMARY KEY,
  system_code text NOT NULL REFERENCES audit.systems(code),
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (system_code, name)
);

CREATE TABLE audit.error_definitions (
  code text PRIMARY KEY,
  system_code text NOT NULL REFERENCES audit.systems(code),
  title text NOT NULL,
  description text,
  created_at timestamptz NOT NULL DEFAULT now(),
  retired_at timestamptz
);

CREATE TABLE audit.traces (
  trace_id uuid PRIMARY KEY,
  operation_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit.audit_events (
  event_id uuid PRIMARY KEY,
  system_code text NOT NULL REFERENCES audit.systems(code),
  service_id uuid REFERENCES audit.services(id),
  event_type text NOT NULL,
  occurred_at timestamptz NOT NULL,
  trace_id uuid REFERENCES audit.traces(trace_id),
  operation_id uuid,
  request_id text,
  source_kind text NOT NULL DEFAULT 'explicit_event' CHECK (source_kind IN ('business_activity', 'operational_event', 'explicit_error', 'explicit_event')),
  source_system text REFERENCES audit.systems(code),
  source_stream text,
  source_record_id text,
  source_transition text,
  source_occurred_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX audit_events_authoritative_source_identity_unique
  ON audit.audit_events
  (source_system, source_stream, source_record_id, source_transition) NULLS NOT DISTINCT
  WHERE source_kind IN ('business_activity', 'operational_event');

CREATE TABLE audit.error_occurrences (
  support_reference uuid PRIMARY KEY,
  error_code text NOT NULL REFERENCES audit.error_definitions(code),
  event_id uuid REFERENCES audit.audit_events(event_id),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit.source_checkpoints (
  source_name text PRIMARY KEY,
  cursor_value text,
  cursor_type text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
