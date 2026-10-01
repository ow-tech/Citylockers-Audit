# Current audit gaps

| System | Capability | Missing evidence | Why it cannot be reconstructed safely | Trigger for fixing | Status |
| --- | --- | --- | --- | --- | --- |
| KH | Booking cancellation history | Dedicated cancellation transition, timestamp, and actor where only current state is retained | Current lifecycle state can overwrite the prior transition | Cancellation feature/change with operator-history requirement | STILL_GAP |
| KH | Booking extension history | Durable extension transition identity and timestamp where no authoritative record is retained | Current booking window does not prove each extension | Extension feature/change with operator-history requirement | STILL_GAP |
| KH | Payment and settlement transition history | Complete durable state-transition record for overwritten processing/settlement state | Current transaction/payment state cannot recreate sequence or timing | Payment/settlement lifecycle change | STILL_GAP |
| KH | Terminal reconciliation history | Durable reconciliation transition where no completed operation record exists | Later records do not prove a reconciliation transition; terminal payment request creation is already exported | Terminal reconciliation workflow change requiring investigation | STILL_GAP |
| KH | Device unpair/replacement attribution | Unpair actor/reason and durable replacement operation identity | Current assignment/install state loses prior intent and identity | Device lifecycle feature/change | STILL_GAP |
| PA | Later Partner transition history | Timestamped durable transition records after request receipt where status is overwritten | `updated_at` and final status do not establish each transition | Partner lifecycle expansion | STILL_GAP |
| KS | Broad unexpected exceptions | Bounded, classified runtime exception evidence beyond sparse operational events | Raw local logs are not central durable evidence | Kiosk error-observability work | INTENTIONALLY_NOT_AUDITED |
