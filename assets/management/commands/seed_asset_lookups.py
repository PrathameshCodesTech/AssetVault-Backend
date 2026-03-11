"""
Management command to seed starter AssetCategory, AssetSubType, BusinessEntity,
and CostCenter records.

Output is clearly labelled as starter seed data.
Idempotent — safe to run multiple times.
"""
from django.core.management.base import BaseCommand

from assets.models import AssetCategory, AssetSubType, BusinessEntity, CostCenter


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

CATEGORIES = [
    {"code": "IT",   "name": "IT Equipment"},
    {"code": "FURN", "name": "Furniture"},
    {"code": "VEH",  "name": "Vehicle"},
]

# (category_code, sub_type_code, sub_type_name)
SUB_TYPES = [
    ("IT",   "LAPTOP",  "Laptop"),
    ("IT",   "DESKTOP", "Desktop"),
    ("FURN", "CHAIR",   "Chair"),
    ("FURN", "DESK",    "Desk"),
    ("VEH",  "SEDAN",   "Sedan"),
]

BUSINESS_ENTITIES = [
    {"code": "OPS",  "name": "Operations"},
    {"code": "TECH", "name": "Technology"},
    {"code": "FIN",  "name": "Finance"},
]

COST_CENTERS = [
    {"code": "CC-IT-001", "name": "IT Operations"},
    {"code": "CC-HR-001", "name": "Human Resources"},
]


class Command(BaseCommand):
    help = "Seed starter AssetCategory, AssetSubType, BusinessEntity, and CostCenter data."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("--- STARTER SEED DATA ---"))

        # ----------------------------------------------------------------
        # AssetCategory
        # ----------------------------------------------------------------
        self.stdout.write("\nSeeding AssetCategory records...")
        cat_map: dict[str, AssetCategory] = {}
        for cat_data in CATEGORIES:
            obj, created = AssetCategory.objects.get_or_create(
                code=cat_data["code"],
                defaults={"name": cat_data["name"]},
            )
            cat_map[obj.code] = obj
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"  [CREATED] AssetCategory: {obj.code} — {obj.name}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"  [SKIPPED] AssetCategory: {obj.code} — already exists")
                )

        # ----------------------------------------------------------------
        # AssetSubType
        # ----------------------------------------------------------------
        self.stdout.write("\nSeeding AssetSubType records...")
        for cat_code, sub_code, sub_name in SUB_TYPES:
            category = cat_map.get(cat_code)
            if category is None:
                self.stdout.write(
                    self.style.ERROR(
                        f"  [SKIP] AssetSubType '{sub_code}': category '{cat_code}' not found."
                    )
                )
                continue

            obj, created = AssetSubType.objects.get_or_create(
                category=category,
                code=sub_code,
                defaults={"name": sub_name},
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [CREATED] AssetSubType: {cat_code}/{sub_code} — {sub_name}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [SKIPPED] AssetSubType: {cat_code}/{sub_code} — already exists"
                    )
                )

        # ----------------------------------------------------------------
        # BusinessEntity
        # ----------------------------------------------------------------
        self.stdout.write("\nSeeding BusinessEntity records...")
        for be_data in BUSINESS_ENTITIES:
            obj, created = BusinessEntity.objects.get_or_create(
                code=be_data["code"],
                defaults={"name": be_data["name"]},
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [CREATED] BusinessEntity: {obj.code} — {obj.name}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [SKIPPED] BusinessEntity: {obj.code} — already exists"
                    )
                )

        # ----------------------------------------------------------------
        # CostCenter
        # ----------------------------------------------------------------
        self.stdout.write("\nSeeding CostCenter records...")
        for cc_data in COST_CENTERS:
            obj, created = CostCenter.objects.get_or_create(
                code=cc_data["code"],
                defaults={"name": cc_data["name"]},
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [CREATED] CostCenter: {obj.code} — {obj.name}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [SKIPPED] CostCenter: {obj.code} — already exists"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS("\n--- STARTER SEED DATA COMPLETE ---")
        )
