"""
Management command to seed LocationTypeRule records.

Defines which parent location types may contain which child location types.
Validates that all referenced LocationType codes exist before creating rules.
Idempotent — safe to run multiple times.
"""
from django.core.management.base import BaseCommand, CommandError

from locations.models import LocationType, LocationTypeRule


# (parent_code, child_code) pairs to seed
RULES = [
    ("country", "region"),
    ("region", "zone"),
    ("zone", "building"),
    ("building", "floor"),
    ("floor", "room"),
]


class Command(BaseCommand):
    help = "Seed LocationTypeRule records (idempotent)."

    def handle(self, *args, **options):
        # ----------------------------------------------------------------
        # Validate that all referenced codes exist before mutating anything
        # ----------------------------------------------------------------
        required_codes = set()
        for parent_code, child_code in RULES:
            required_codes.add(parent_code)
            required_codes.add(child_code)

        existing_codes = set(
            LocationType.objects.filter(code__in=required_codes).values_list(
                "code", flat=True
            )
        )
        missing_codes = required_codes - existing_codes
        if missing_codes:
            raise CommandError(
                f"Cannot seed LocationTypeRules — the following LocationType codes are "
                f"missing from the database: {sorted(missing_codes)}. "
                f"Run 'seed_location_types' first."
            )

        # Build a lookup dict so we avoid repeated queries in the loop
        lt_map: dict[str, LocationType] = {
            lt.code: lt
            for lt in LocationType.objects.filter(code__in=required_codes)
        }

        # ----------------------------------------------------------------
        # Upsert rules
        # ----------------------------------------------------------------
        created_count = 0
        updated_count = 0

        for parent_code, child_code in RULES:
            parent_type = lt_map[parent_code]
            child_type = lt_map[child_code]

            obj, created = LocationTypeRule.objects.update_or_create(
                parent_type=parent_type,
                child_type=child_type,
                defaults={"is_active": True},
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [CREATED] Rule: {parent_code} -> {child_code}"
                    )
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  [UPDATED] Rule: {parent_code} -> {child_code}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created {created_count} rules, updated {updated_count} rules."
            )
        )
