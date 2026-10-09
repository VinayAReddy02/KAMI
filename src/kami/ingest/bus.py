"""Message bus interface with an in-process and an MQTT backend."""
from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from typing import Callable

Handler = Callable[[str, dict], None]


def topic_matches(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    for i, seg in enumerate(p):
        if seg == "#":
            return True
        if i >= len(t) or (seg != "+" and seg != t[i]):
            return False
    return len(p) == len(t)


class Bus(ABC):
    @abstractmethod
    def publish(self, topic: str, payload: dict) -> None: ...

    @abstractmethod
    def subscribe(self, pattern: str, handler: Handler) -> None: ...

    def close(self) -> None:
        pass


class InProcessBus(Bus):
    """Synchronous in-process pub/sub (handlers run in the publishing thread)."""

    def __init__(self):
        self._subs: list[tuple[str, Handler]] = []
        self._lock = threading.Lock()

    def publish(self, topic, payload):
        with self._lock:
            subs = list(self._subs)
        # round-trip through JSON so both backends deliver identical payloads
        data = json.loads(json.dumps(payload))
        for pat, h in subs:
            if topic_matches(pat, topic):
                h(topic, data)

    def subscribe(self, pattern, handler):
        with self._lock:
            self._subs.append((pattern, handler))


class MqttBus(Bus):
    def __init__(self, host: str = "localhost", port: int = 1883):
        import paho.mqtt.client as mqtt

        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._handlers: list[tuple[str, Handler]] = []
        self._c.on_message = self._on_message
        self._c.connect(host, port, keepalive=30)
        self._c.loop_start()

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        for pat, h in list(self._handlers):
            if topic_matches(pat, msg.topic):
                h(msg.topic, data)

    def publish(self, topic, payload):
        self._c.publish(topic, json.dumps(payload), qos=0)

    def subscribe(self, pattern, handler):
        self._handlers.append((pattern, handler))
        self._c.subscribe(pattern, qos=0)

    def close(self):
        self._c.loop_stop()
        self._c.disconnect()


def make_bus(mode: str) -> Bus:
    from .. import config

    if mode == "docker":
        return MqttBus("localhost", config.MQTT_PORT)
    return InProcessBus()
