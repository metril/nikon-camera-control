import asyncio

import pytest

from backend.api.schemas.common import EventType
from backend.core.errors import CameraBusy, JobNotFound, SettingInvalid
from backend.core.events import EventBus
from backend.core.jobs import JobManager, JobStatus


@pytest.fixture
def bus():
    return EventBus(queue_size=1000)


@pytest.fixture
async def events(bus):
    sub = bus.subscribe()

    def drain(type_=None):
        out = []
        while not sub._queue.empty():
            ev = sub._queue.get_nowait()
            if ev is not None and (type_ is None or ev.type == type_):
                out.append(ev)
        return out

    return drain


async def wait_done(mgr, job_id):
    for _ in range(200):
        if mgr.get(job_id).status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return mgr.get(job_id)
        await asyncio.sleep(0)
    raise AssertionError("job did not finish")


async def test_completed(bus, events):
    mgr = JobManager(bus)

    async def work(ctx):
        return {"x": 1}

    job = mgr.submit("video", work)
    assert job.status == JobStatus.QUEUED
    done = await wait_done(mgr, job.id)
    assert done.status == JobStatus.COMPLETED
    assert done.result == {"x": 1} and done.progress == 1.0
    assert done.started and done.finished
    types = [e.type for e in events()]
    assert types[0] == EventType.JOB_CREATED and types[-1] == EventType.JOB_COMPLETED


async def test_failed_generic_and_app_error(bus, events):
    mgr = JobManager(bus)

    async def boom(ctx):
        raise RuntimeError("kaput")

    async def app(ctx):
        raise SettingInvalid("bad value")

    j1, j2 = mgr.submit("a", boom), mgr.submit("b", app)
    d1, d2 = await wait_done(mgr, j1.id), await wait_done(mgr, j2.id)
    assert d1.status == JobStatus.FAILED and d1.error == "kaput" and d1.error_code is None
    assert d2.error == "bad value" and d2.error_code == "SETTING_INVALID"
    assert len(events(EventType.JOB_FAILED)) == 2


async def test_cancel_running(bus, events):
    mgr = JobManager(bus)
    started = asyncio.Event()

    async def work(ctx):
        started.set()
        await asyncio.sleep(10)
        return {}

    job = mgr.submit("a", work)
    await started.wait()
    out = await mgr.cancel(job.id)
    assert out.status == JobStatus.CANCELLED
    assert len(events(EventType.JOB_CANCELLED)) == 1
    again = await mgr.cancel(job.id)  # no-op on finished
    assert again.status == JobStatus.CANCELLED
    assert len(events(EventType.JOB_CANCELLED)) == 0


async def test_cancel_before_start_and_unknown(bus):
    mgr = JobManager(bus)

    async def work(ctx):
        return {}

    job = mgr.submit("a", work)
    assert (await mgr.cancel(job.id)).status == JobStatus.CANCELLED
    with pytest.raises(JobNotFound):
        await mgr.cancel("nope")
    with pytest.raises(JobNotFound):
        mgr.get("nope")


async def test_cancel_sets_ctx_cancelled_flag(bus):
    mgr = JobManager(bus)
    seen = []
    started = asyncio.Event()

    async def work(ctx):
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            seen.append(ctx.cancelled)
        return {}

    job = mgr.submit("a", work)
    await started.wait()
    await mgr.cancel(job.id)
    assert seen == [True]


async def test_progress_clamped_and_throttled(bus, events):
    t = [0.0]
    mgr = JobManager(bus, clock=lambda: t[0])

    async def work(ctx):
        ctx.report(-5, "neg")
        for i in range(1, 10):  # all within the throttle window
            t[0] += 0.01
            ctx.report(i / 10)
        t[0] += 0.5
        ctx.report(7)  # clamped to 1.0, always published
        return {}

    job = mgr.submit("a", work)
    await wait_done(mgr, job.id)
    prog = events(EventType.JOB_PROGRESS)
    assert len(prog) == 2
    assert prog[0].data["job"]["progress"] == 0.0
    assert prog[-1].data["job"]["progress"] == 1.0


async def test_final_progress_published_within_window(bus, events):
    mgr = JobManager(bus, clock=lambda: 0.0)

    async def work(ctx):
        ctx.report(0.5)
        ctx.report(1.0)
        return {}

    await wait_done(mgr, mgr.submit("a", work).id)
    assert [e.data["job"]["progress"] for e in events(EventType.JOB_PROGRESS)] == [0.5, 1.0]


async def test_retention_cap_and_list_filters(bus):
    mgr = JobManager(bus, max_finished=3)

    async def work(ctx):
        return {}

    ids = []
    for i in range(6):
        j = mgr.submit("k1" if i % 2 else "k2", work)
        await wait_done(mgr, j.id)
        ids.append(j.id)
    assert len(mgr.list()) == 3
    with pytest.raises(JobNotFound):
        mgr.get(ids[0])
    assert mgr.get(ids[-1])
    assert all(j.kind == "k1" for j in mgr.list(kind="k1"))
    assert mgr.list(status=JobStatus.RUNNING) == []


async def test_exclusive_key(bus):
    mgr = JobManager(bus)
    gate = asyncio.Event()

    async def work(ctx):
        await gate.wait()
        return {}

    j1 = mgr.submit("video", work, exclusive_key="s1")
    with pytest.raises(CameraBusy):
        mgr.submit("video", work, exclusive_key="s1")
    other = mgr.submit("video", work, exclusive_key="s2")  # different key ok
    gate.set()
    await wait_done(mgr, j1.id)
    await wait_done(mgr, other.id)
    again = mgr.submit("video", work, exclusive_key="s1")  # released
    await wait_done(mgr, again.id)


async def test_exclusive_key_released_on_cancel(bus):
    mgr = JobManager(bus)

    async def work(ctx):
        await asyncio.sleep(10)
        return {}

    j = mgr.submit("v", work, exclusive_key="k")
    await mgr.cancel(j.id)
    await mgr.cancel(mgr.submit("v", work, exclusive_key="k").id)


async def test_shutdown_cancels_all(bus):
    mgr = JobManager(bus)

    async def work(ctx):
        await asyncio.sleep(10)
        return {}

    ids = [mgr.submit("a", work).id for _ in range(3)]
    await asyncio.sleep(0)
    await mgr.shutdown()
    assert all(mgr.get(i).status == JobStatus.CANCELLED for i in ids)
