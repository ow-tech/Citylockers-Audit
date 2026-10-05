#!/usr/bin/env python3
"""Run the real Bridge MQTT callback and synthetic kiosk publisher against local-only services."""

from __future__ import annotations

import json
import os
import sys
import time
from uuid import UUID

import paho.mqtt.client as mqtt
import redis

from locker_gateway_bridge.main import build_client, build_kiosk_audit_relay
from locker_gateway_bridge.mqtt.topics import locker_event_topic


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    outage = "--outage" in sys.argv[1:]
    mqtt_host, mqtt_port = os.environ["AUDIT_SMOKE_MQTT_HOST"], int(os.environ["AUDIT_SMOKE_MQTT_PORT"])
    redis.Redis.from_url(os.environ["AUDIT_SMOKE_REDIS_URL"], socket_timeout=2).ping()
    relay = build_kiosk_audit_relay()
    require(relay is not None, "Bridge audit relay was not configured")
    bridge = build_client(kiosk_audit_relay=relay, owns_device=lambda _device: True, bridge_instance_key="local-smoke")
    bridge.connect(mqtt_host, mqtt_port, keepalive=10)
    bridge.loop_start()
    try:
        deadline = time.monotonic() + 5
        while not bridge.is_connected() and time.monotonic() < deadline:
            time.sleep(0.05)
        require(bridge.is_connected(), "Bridge did not connect to local Mosquitto")
        result, _ = bridge.subscribe(locker_event_topic("smoke-kiosk"), qos=1)
        require(result == mqtt.MQTT_ERR_SUCCESS, "Bridge did not subscribe to kiosk event topic")
        publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="synthetic-kiosk-audit-smoke")
        publisher.connect(mqtt_host, mqtt_port, keepalive=10)
        publisher.loop_start()
        try:
            payload = {
                "event_id": "00000000-0000-4000-8000-000000000201", "locker_uuid": "smoke-locker-1",
                "timestamp": "2026-10-03T12:00:00Z", "hook_released": "released",
                "trace_id": "00000000-0000-4000-8000-000000000202", "operation_id": "00000000-0000-4000-8000-000000000203",
                "request_id": "00000000-0000-4000-8000-000000000204", "access_code": "must-not-leave-kiosk",
            }
            info = publisher.publish(locker_event_topic("smoke-kiosk"), json.dumps(payload), qos=1, retain=False)
            info.wait_for_publish(timeout=3)
            require(info.is_published(), "synthetic kiosk did not publish")
            # The relay runs on a daemon thread. Giving it a small bounded window also
            # proves a refused central endpoint does not block MQTT command flow.
            time.sleep(0.35 if outage else 0.8)
        finally:
            publisher.loop_stop()
            publisher.disconnect()
    finally:
        bridge.loop_stop()
        bridge.disconnect()
    print("bridge-outage=PASS" if outage else "bridge-relay=PASS")


if __name__ == "__main__":
    main()
