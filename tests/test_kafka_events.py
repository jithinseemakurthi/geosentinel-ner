"""Tests for the Kafka event backbone (producer, consumer, topics, event bus)."""
import asyncio
from uuid import uuid4

from geosentinel_shared import (
    EventTopics,
    GeoSentinelEvent,
    InMemoryEventBus,
    KafkaConsumerClient,
    KafkaProducerClient,
    get_in_memory_event_bus,
)


class TestEventSchemas:
    def test_event_serialization_and_deserialization(self):
        alert_id = uuid4()
        event = GeoSentinelEvent(
            event_type="alert.triggered",
            topic=EventTopics.ALERT_TRIGGERED,
            source_service="alert-engine",
            correlation_id=alert_id,
            payload={
                "alert_id": str(alert_id),
                "severity": "critical",
                "zone_name": "Aizawl Ridge",
                "risk_score": 0.88,
            },
        )

        raw_bytes = event.to_json_bytes()
        assert isinstance(raw_bytes, bytes)

        restored = GeoSentinelEvent.from_json_bytes(raw_bytes)
        assert restored.event_id == event.event_id
        assert restored.event_type == "alert.triggered"
        assert restored.topic == EventTopics.ALERT_TRIGGERED
        assert restored.payload["severity"] == "critical"
        assert restored.payload["risk_score"] == 0.88


class TestInMemoryEventBus:
    async def test_publish_and_subscribe(self):
        bus = InMemoryEventBus()
        received = []

        def handle_event(evt: GeoSentinelEvent):
            received.append(evt)

        bus.subscribe(EventTopics.WEATHER_OBSERVED, handle_event)

        event = GeoSentinelEvent(
            event_type="weather.observed",
            topic=EventTopics.WEATHER_OBSERVED,
            source_service="data-ingestion",
            payload={"station_id": "AWS-001", "rainfall_mm": 45.2},
        )
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].payload["rainfall_mm"] == 45.2

    async def test_async_handler_execution(self):
        bus = InMemoryEventBus()
        received = []

        async def async_handler(evt: GeoSentinelEvent):
            await asyncio.sleep(0.01)
            received.append(evt)

        bus.subscribe(EventTopics.REPORT_SUBMITTED, async_handler)

        event = GeoSentinelEvent(
            event_type="report.submitted",
            topic=EventTopics.REPORT_SUBMITTED,
            source_service="report-service",
            payload={"report_code": "GSN-2024-001"},
        )
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].payload["report_code"] == "GSN-2024-001"


class TestKafkaProducerAndConsumerClients:
    async def test_producer_fallback_to_in_memory_bus(self):
        producer = KafkaProducerClient()
        await producer.start()

        bus = get_in_memory_event_bus()
        received = []
        bus.subscribe(EventTopics.NOTIFICATION_DISPATCH, lambda e: received.append(e))

        evt = await producer.publish(
            topic=EventTopics.NOTIFICATION_DISPATCH,
            event_type="notification.dispatch",
            source_service="alert-engine",
            payload={"alert_id": "123", "channels": ["sms", "push"]},
        )

        assert evt.topic == EventTopics.NOTIFICATION_DISPATCH
        assert any(e.event_id == evt.event_id for e in received)
        await producer.stop()

    async def test_consumer_client_in_memory_dispatch(self):
        consumer = KafkaConsumerClient(
            service_name="notification-service",
            topics=[EventTopics.ALERT_TRIGGERED],
        )
        received = []

        consumer.register_handler(
            EventTopics.ALERT_TRIGGERED,
            lambda e: received.append(e),
        )
        await consumer.start()

        producer = KafkaProducerClient()
        await producer.start()

        await producer.publish(
            topic=EventTopics.ALERT_TRIGGERED,
            event_type="alert.triggered",
            source_service="alert-engine",
            payload={"alert_id": "999", "severity": "evacuation"},
        )

        assert len(received) >= 1
        assert received[-1].payload["severity"] == "evacuation"

        await consumer.stop()
        await producer.stop()
