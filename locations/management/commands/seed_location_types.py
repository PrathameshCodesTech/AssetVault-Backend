"""
Management command to seed standard LocationType records.

Idempotent — safe to run multiple times. Existing records are updated
in-place; new records are created as needed.
"""
from django.core.management.base import BaseCommand

from locations.models import LocationType


LOCATION_TYPES = [
    {
        "code": "country",
        "name": "Country",
        "sort_order": 10,
        "can_hold_assets": False,
    },
    {
        "code": "region",
        "name": "Region",
        "sort_order": 20,
        "can_hold_assets": False,
    },
    {
        "code": "zone",
        "name": "Zone",
        "sort_order": 30,
        "can_hold_assets": False,
    },
    {
        "code": "building",
        "name": "Building",
        "sort_order": 40,
        "can_hold_assets": True,
    },
    {
        "code": "floor",
        "name": "Floor",
        "sort_order": 50,
        "can_hold_assets": True,
    },
    {
        "code": "room",
        "name": "Room",
        "sort_order": 60,
        "can_hold_assets": True,
    },
]


class Command(BaseCommand):
    help = "Seed standard LocationType records (idempotent)."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for lt_data in LOCATION_TYPES:
            obj, created = LocationType.objects.update_or_create(
                code=lt_data["code"],
                defaults={
                    "name": lt_data["name"],
                    "sort_order": lt_data["sort_order"],
                    "can_hold_assets": lt_data["can_hold_assets"],
                },
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [CREATED] LocationType: {obj.code!r} ({obj.name})"
                    )
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  [UPDATED] LocationType: {obj.code!r} ({obj.name})"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created {created_count} location types, "
                f"updated {updated_count} location types."
            )
        )
