import asyncio
import threading
from datetime import UTC

import pytest

from backend.api.schemas.common import EventType
from backend.core.events import EventBus


async def test_publish_on_loop_delivers_with_utc_ts():
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish(EventType.BATTERY, {"level": 5})
    ev = await asyncio.wait_for(anext(sub), 1)
    assert ev.type == EventType.BATTERY
    assert ev.data == {"level": 5}
    assert ev.ts.tzinfo is not None and ev.ts.utcoffset() == UTC.utcoffset(None)


async def test_publish_from_thread():
    bus = EventBus()
    sub = bus.subscribe()
    t = threading.Thread(target=bus.publish, args=(EventType.CAMERA_STATE, {"n": 1}))
    t.start()
    ev = await asyncio.wait_for(anext(sub), 1)
    t.join()
    assert ev.data == {"n": 1}


def test_publish_before_loop_bound_and_after_close_is_noop():
    bus = EventBus()
    bus.publish(EventType.ERROR)  # no loop bound
    bus.close()
    bus.publish(EventType.ERROR)


async def test_slow_subscriber_dropped_others_unaffected():
    bus = EventBus(queue_size=2)
    slow, fast = bus.subscribe(), bus.subscribe()
    for i in range(2):
        bus.publish(EventType.BATTERY, {"i": i})
        assert (await anext(fast)).data == {"i": i}
    bus.publish(EventType.BATTERY, {"i": 2})  # slow now has 3 pending > 2
    assert slow.dropped and not fast.dropped
    assert bus.subscriber_count == 1
    with pytest.raises(StopAsyncIteration):
        await anext(slow)
    assert (await anext(fast)).data == {"i": 2}
    bus.publish(EventType.BATTERY, {"i": 3})
    assert (await anext(fast)).data == {"i": 3}


async def test_unsubscribe_during_publish_is_safe():
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    a.close()
    bus.publish(EventType.ERROR)
    assert (await anext(b)).type == EventType.ERROR
    a.close()  # idempotent
    assert bus.subscriber_count == 1


async def test_close_ends_all_iterators():
    bus = EventBus()
    sub = bus.subscribe()
    got = []

    async def consume():
        async for ev in sub:
            got.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    bus.publish(EventType.ERROR)
    await asyncio.sleep(0)
    bus.close()
    await asyncio.wait_for(task, 1)
    assert not sub.dropped
    assert bus.subscriber_count == 0
    bus.publish(EventType.ERROR)  # no-op


async def test_context_manager_unsubscribes():
    bus = EventBus()
    async with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0
