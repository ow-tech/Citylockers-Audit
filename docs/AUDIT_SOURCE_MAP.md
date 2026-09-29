# Audit source map

The following are candidates only. Repository-specific recon must prove their current schema and transition semantics before an adapter is implemented.

| Producer | Candidate authoritative sources |
| --- | --- |
| Khizana | `booking.bookings`, `booking.transactions`, `booking.terminal_payment_attempts`, `booking.bridge_switch_operations`, `booking.device_installs` |
| Partner API | `partner.bridge_requests` |
| LockerGatewayBridge | existing bridge `event_id` chain, `bridge_events` lifecycle, processed-event state, device ACK state |
| CityLockers App | Backend-originated successful activity must not be duplicated; only client-only failures/evidence gaps need explicit emission. |
| Kiosk | Deferred. |
