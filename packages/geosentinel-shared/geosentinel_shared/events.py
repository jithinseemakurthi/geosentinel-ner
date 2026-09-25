"""
GeoSentinel-NER Kafka Event Backbone.
Provides event schemas, async producer, async consumer, and in-memory mock fallback.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .config import settings
from .logging import get_logger

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Event Topics
# -----------------------------------------------------------------------------
class EventTopics:
    WEATHER_OBSERVED = "geosentinel.weather.observed"
    WEATHER_FORECAST = "geosentinel.weather.forecast"
    SENSOR_TELEMETRY = "geosentinel.sensor.telemetry"
    REPORT_SUBMITTED = "geosentinel.report.submitted"
    REPORT_TRIAGED = "geosentinel.report.triaged"
    RISK_CALCULATED = "geosentinel.risk.calculated"
    ALERT_TRIGGERED = "geosentinel.alert.triggered"
    NOTIFICATION_DISPATCH = "geosentinel.notification.dispatch"
    NOTIFICATION_STATUS = "geosentinel.notification.status"


# -----------------------------------------------------------------------------
# Base Event Schema
# -----------------------------------------------------------------------------
class GeoSentinelEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    topic: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_service: str
    correlation_id: Optional[UUID] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    def to_json_bytes(self) -> bytes:
        data = self.model_dump(mode="json")
        return json.dumps(data).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> "GeoSentinelEvent":
        data = json.loads(raw.decode("utf-8"))
        return cls.model_validate(data)


# -----------------------------------------------------------------------------
# In-Memory Event Bus (Development / Test Fallback)
# -----------------------------------------------------------------------------
class InMemoryEventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[GeoSentinelEvent], Any]]] = {}
        self.published_events: List[GeoSentinelEvent] = []

    def subscribe(self, topic: str, handler: Callable[[GeoSentinelEvent], Any]):
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(handler)

    async def publish(self, event: GeoSentinelEvent):
        self.published_events.append(event)
        handlers = self._subscribers.get(event.topic, [])
        for handler in handlers:
            try:
                res = handler(event)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.error("event_handler_failed", topic=event.topic, error=str(exc))


_in_memory_bus = InMemoryEventBus()


def get_in_memory_event_bus() -> InMemoryEventBus:
    return _in_memory_bus


# -----------------------------------------------------------------------------
# Kafka Producer Client
# -----------------------------------------------------------------------------
class KafkaProducerClient:
    def __init__(self):
        self.enabled = settings.ENABLE_KAFKA
        self.bootstrap_servers = settings.KAFKA_BOOTSTRAP_SERVERS
        self._producer = None
        self._bus = get_in_memory_event_bus()

    async def start(self):
        if not self.enabled:
            logger.info("kafka_producer_disabled_using_in_memory_bus")
            return
        try:
            from aiokafka import AIOKafkaProducer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: str(k).encode("utf-8") if k else None,
            )
            await self._producer.start()
            logger.info("kafka_producer_started", bootstrap=self.bootstrap_servers)
        except Exception as exc:
            logger.warning("kafka_producer_start_failed_falling_back_to_bus", error=str(exc))
            self._producer = None

    async def stop(self):
        if self._producer:
            await self._producer.stop()
            logger.info("kafka_producer_stopped")

    async def publish(
        self,
        topic: str,
        event_type: str,
        source_service: str,
        payload: Dict[str, Any],
        key: Optional[str] = None,
        correlation_id: Optional[UUID] = None,
    ) -> GeoSentinelEvent:
        """Publish an event to a Kafka topic or the in-memory bus."""
        event = GeoSentinelEvent(
            event_type=event_type,
            topic=topic,
            source_service=source_service,
            correlation_id=correlation_id,
            payload=payload,
        )

        if self._producer is not None:
            try:
                await self._producer.send_and_wait(
                    topic=topic,
                    key=key,
                    value=event.model_dump(mode="json"),
                )
                logger.debug("kafka_event_published", topic=topic, event_id=str(event.event_id))
            except Exception as exc:
                logger.error("kafka_publish_failed", topic=topic, error=str(exc))
                await self._bus.publish(event)
        else:
            await self._bus.publish(event)

        return event


# -----------------------------------------------------------------------------
# Kafka Consumer Client
# -----------------------------------------------------------------------------
class KafkaConsumerClient:
    def __init__(self, service_name: str, topics: List[str]):
        self.service_name = service_name
        self.topics = topics
        self.enabled = settings.ENABLE_KAFKA
        self.bootstrap_servers = settings.KAFKA_BOOTSTRAP_SERVERS
        self.group_id = f"{settings.KAFKA_CONSUMER_GROUP}-{service_name}"
        self._consumer = None
        self._handlers: Dict[str, List[Callable[[GeoSentinelEvent], Any]]] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._bus = get_in_memory_event_bus()

    def register_handler(self, topic: str, handler: Callable[[GeoSentinelEvent], Any]):
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)
        self._bus.subscribe(topic, handler)

    async def start(self):
        self._running = True
        if not self.enabled:
            logger.info("kafka_consumer_disabled_listening_in_memory", service=self.service_name)
            return

        try:
            from aiokafka import AIOKafkaConsumer
            self._consumer = AIOKafkaConsumer(
                *self.topics,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="latest",
                enable_auto_commit=True,
            )
            await self._consumer.start()
            self._task = asyncio.create_task(self._consume_loop())
            logger.info("kafka_consumer_started", service=self.service_name, topics=self.topics)
        except Exception as exc:
            logger.warning("kafka_consumer_start_failed_using_in_memory", error=str(exc))
            self._consumer = None

    async def _consume_loop(self):
        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                try:
                    event = GeoSentinelEvent.model_validate(msg.value)
                    handlers = self._handlers.get(msg.topic, [])
                    for h in handlers:
                        res = h(event)
                        if asyncio.iscoroutine(res):
                            await res
                except Exception as exc:
                    logger.error("kafka_message_processing_error", topic=msg.topic, error=str(exc))
        except asyncio.CancelledError:
            pass

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        if self._consumer:
            await self._consumer.stop()
            logger.info("kafka_consumer_stopped", service=self.service_name)


# Singletons
event_producer = KafkaProducerClient()
