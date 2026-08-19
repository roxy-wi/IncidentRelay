
from app.db import init_database
from app.modules.db.models import (
    Rotation,
    RotationMember,
    RotationLayer,
    RotationLayerMember,
    RotationLayerRestriction,
)
from app.modules.common import utc_now

db = init_database()


def upgrade():
    """Create rotation layers and migrate current rotation members into default layers."""

    db.create_tables(
        [
            RotationLayer,
            RotationLayerMember,
            RotationLayerRestriction,
        ],
        safe=True,
    )

    for rotation in Rotation.select():
        layer, _ = RotationLayer.get_or_create(
            rotation=rotation,
            name="Default layer",
            defaults={
                "description": "Migrated from rotation members",
                "priority": 0,
                "start_at": rotation.start_at,
                "duration_seconds": rotation.duration_seconds,
                "rotation_type": rotation.rotation_type,
                "interval_value": rotation.interval_value,
                "interval_unit": rotation.interval_unit,
                "handoff_time": rotation.handoff_time,
                "handoff_weekday": rotation.handoff_weekday,
                "timezone": rotation.timezone,
                "enabled": rotation.enabled,
                "created_at": utc_now(),
            },
        )

        for member in (
            RotationMember.select()
            .where(RotationMember.rotation == rotation)
            .order_by(RotationMember.position.asc(), RotationMember.id.asc())
        ):
            RotationLayerMember.get_or_create(
                layer=layer,
                user=member.user,
                defaults={
                    "position": member.position,
                    "active": member.active,
                },
            )


def downgrade():
    """Drop rotation layer tables."""

    db.drop_tables(
        [
            RotationLayerRestriction,
            RotationLayerMember,
            RotationLayer,
        ],
        safe=True,
    )
