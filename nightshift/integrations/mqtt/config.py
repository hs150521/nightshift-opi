"""MQTT configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MqttConfig:
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    node_id: str
    base_topic: str
    keepalive: int
    tls_enabled: bool
    ca_file: str

    @classmethod
    def from_env(cls, node_id: str) -> MqttConfig:
        import os

        return cls(
            enabled=os.getenv("NIGHTSHIFT_MQTT_ENABLED", "false").lower() == "true",
            host=os.getenv("NIGHTSHIFT_MQTT_HOST", "127.0.0.1"),
            port=int(os.getenv("NIGHTSHIFT_MQTT_PORT", "1883")),
            username=os.getenv("NIGHTSHIFT_MQTT_USERNAME", ""),
            password=os.getenv("NIGHTSHIFT_MQTT_PASSWORD", ""),
            node_id=os.getenv("NIGHTSHIFT_MQTT_NODE_ID", node_id),
            base_topic=os.getenv("NIGHTSHIFT_MQTT_BASE_TOPIC", "nightshift/v1").rstrip("/"),
            keepalive=int(os.getenv("NIGHTSHIFT_MQTT_KEEPALIVE", "30")),
            tls_enabled=os.getenv("NIGHTSHIFT_MQTT_TLS_ENABLED", "false").lower() == "true",
            ca_file=os.getenv("NIGHTSHIFT_MQTT_CA_FILE", ""),
        )
