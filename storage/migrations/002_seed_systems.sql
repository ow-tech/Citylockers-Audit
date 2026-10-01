INSERT INTO audit.systems (code, name) VALUES
  ('CL', 'CityLockers'),
  ('KH', 'Khizana'),
  ('PA', 'Partner API'),
  ('BR', 'LockerGatewayBridge'),
  ('KS', 'Kiosk gateway'),
  ('AU', 'Central Audit')
ON CONFLICT (code) DO NOTHING;
