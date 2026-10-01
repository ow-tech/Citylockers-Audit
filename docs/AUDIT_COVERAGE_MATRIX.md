# Audit coverage matrix

| System | Owns / authoritative source | Evidence emitted or exported | Intentionally does not emit | Known gaps |
| --- | --- | --- | --- | --- |
| CL | Consumer UI; Khizana remains business authority | Bounded client-only `CL-*` errors through the Worker | Booking/payment success, normal navigation/clicks, backend-originated errors | Browser unexpected failures outside integrated seams |
| KH | Bookings, payments, refunds, reversals, terminal/bridge/device operations | Durable allowlisted export from booking/finance records; Audit & Errors query proxy | Duplicate happy-path runtime events | Mutable lifecycle and payment transitions where no dedicated durable record exists |
| PA | Partner request activity | `partner.bridge_requests`; bounded `PA-*` runtime errors | Duplicate successful booking/payment events; replay errors | Later transition history only where request state is overwritten |
| BR | MQTT delivery, retries, acknowledgements, correlation relay | Preserves correlation and relays sparse KS evidence / BR-specific runtime evidence | Parallel happy-path activity store | None recorded beyond upstream source gaps |
| KS | Local physical execution and device state | Sparse `locker.unlock_actuation_sent` evidence with controller result | Heartbeats, raw logs, or a claim that a door opened without physical proof | Broad unexpected-exception evidence is not centrally emitted |
| AU | Central evidence, error catalogue, correlation, query, privacy boundary | Canonical stored events/errors and read-only operator queries | Operational decision making or critical-path dependency | Source coverage is limited to integrated producers |
