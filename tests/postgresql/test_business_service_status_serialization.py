"""PostgreSQL must serialize Business Service status/history calculations."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.db import database_proxy
from app.modules.db.models import (
    BusinessService,
    BusinessServiceComponent,
    BusinessServiceStatusHistory,
)
from app.services.business_services.status import apply_business_service_status
from tests.factories import create_group, create_service, create_team, unique

pytestmark = pytest.mark.postgresql


def test_concurrent_status_recalculation_writes_one_history_transition(db):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")

    group = create_group()
    team = create_team(group)
    service = create_service(team, slug=unique("lock-technical"))
    service.status = "major_outage"
    service.save()
    business = BusinessService.create(
        group=group,
        slug=unique("lock-business"),
        name="Business",
        status="unknown",
        enabled=True,
    )
    BusinessServiceComponent.create(
        business_service=business,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    lock_held = Event()
    release_lock = Event()
    second_started = Event()
    second_done = Event()

    def first_worker():
        with database_proxy.obj.connection_context():
            with database_proxy.atomic():
                (BusinessService.select()
                 .where(BusinessService.id == business.id)
                 .for_update().get())
                lock_held.set()
                assert release_lock.wait(timeout=10)
                return apply_business_service_status(business)["status"]

    def second_worker():
        with database_proxy.obj.connection_context():
            assert lock_held.wait(timeout=10)
            second_started.set()
            try:
                return apply_business_service_status(business)["status"]
            finally:
                second_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_worker)
        second = pool.submit(second_worker)
        try:
            assert second_started.wait(timeout=10)
            assert not second_done.wait(timeout=0.1)
        finally:
            release_lock.set()
        assert first.result(timeout=20) == "major_outage"
        assert second.result(timeout=20) == "major_outage"

    transitions = list(BusinessServiceStatusHistory.select().where(
        BusinessServiceStatusHistory.business_service == business.id
    ))
    assert len(transitions) == 1
    assert transitions[0].old_status == "unknown"
    assert transitions[0].new_status == "major_outage"
