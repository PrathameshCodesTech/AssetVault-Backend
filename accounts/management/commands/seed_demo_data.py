"""
Management command to seed demo data for development and testing.

Creates sample users, role assignments (scoped where appropriate), locations,
assets with proper AssetAssignment rows, one verification cycle with
snapshotted assets, and one pending field submission. Idempotent.
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Seed demo data: users, role assignments, locations, assets, verification cycle, submission (idempotent)."

    def handle(self, *args, **options):
        from access.models import Role, UserRoleAssignment
        from accounts.models import User
        from assets.models import Asset, AssetAssignment, AssetCategory
        from assets.services.asset_service import assign_asset
        from locations.models import LocationNode, LocationType
        from submissions.models import FieldSubmission
        from verification.models import VerificationCycle, VerificationRequest
        from verification.services.request_service import (
            create_verification_request,
            snapshot_request_assets,
        )

        # ==================================================================
        # 1. Users
        # ==================================================================
        self.stdout.write("Seeding demo users...")

        admin_user, created = User.objects.get_or_create(
            email="admin@demo.local",
            defaults={
                "first_name": "Demo",
                "last_name": "Admin",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin_user.set_unusable_password()
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("  [CREATED] admin@demo.local"))
        else:
            self.stdout.write("  [EXISTS] admin@demo.local")

        loc_admin_user, created = User.objects.get_or_create(
            email="locadmin@demo.local",
            defaults={"first_name": "Location", "last_name": "Admin"},
        )
        if created:
            loc_admin_user.set_unusable_password()
            loc_admin_user.save()
            self.stdout.write(self.style.SUCCESS("  [CREATED] locadmin@demo.local"))
        else:
            self.stdout.write("  [EXISTS] locadmin@demo.local")

        employee_user, created = User.objects.get_or_create(
            email="employee@demo.local",
            defaults={
                "first_name": "Demo",
                "last_name": "Employee",
                "employee_code": "EMP-001",
            },
        )
        if created:
            employee_user.set_unusable_password()
            employee_user.save()
            self.stdout.write(self.style.SUCCESS("  [CREATED] employee@demo.local"))
        else:
            self.stdout.write("  [EXISTS] employee@demo.local")

        # ==================================================================
        # 2. Locations
        # ==================================================================
        self.stdout.write("Seeding demo locations...")

        country_type = LocationType.objects.filter(code="country").first()
        region_type = LocationType.objects.filter(code="region").first()
        zone_type = LocationType.objects.filter(code="zone").first()
        building_type = LocationType.objects.filter(code="building").first()
        floor_type = LocationType.objects.filter(code="floor").first()

        demo_country = demo_region = demo_zone = demo_building = demo_floor = None

        if country_type:
            demo_country, created = LocationNode.objects.get_or_create(
                code="DEMO-IN", location_type=country_type, parent=None,
                defaults={"name": "India"},
            )
            self._log(created, "India (country)")
        else:
            self.stdout.write(self.style.WARNING(
                "  [SKIP] 'country' location type not found — run seed_location_types first."
            ))

        if region_type and demo_country:
            demo_region, created = LocationNode.objects.get_or_create(
                code="DEMO-WEST", location_type=region_type, parent=demo_country,
                defaults={"name": "West Region"},
            )
            self._log(created, "West Region")

        if zone_type and demo_region:
            demo_zone, created = LocationNode.objects.get_or_create(
                code="DEMO-MUM", location_type=zone_type, parent=demo_region,
                defaults={"name": "Mumbai Zone"},
            )
            self._log(created, "Mumbai Zone")

        if building_type and demo_zone:
            demo_building, created = LocationNode.objects.get_or_create(
                code="HQ-BLDG-1", location_type=building_type, parent=demo_zone,
                defaults={"name": "HQ Building 1"},
            )
            self._log(created, "HQ Building 1")

        if floor_type and demo_building:
            demo_floor, created = LocationNode.objects.get_or_create(
                code="FLOOR-1", location_type=floor_type, parent=demo_building,
                defaults={"name": "Floor 1"},
            )
            self._log(created, "Floor 1")

        asset_location = demo_floor or demo_building or demo_zone

        # ==================================================================
        # 3. Role assignments (scoped)
        # ==================================================================
        self.stdout.write("Assigning roles...")

        scope_root = demo_zone or demo_building or demo_country

        role_assignments = [
            ("super_admin", admin_user, None),
            ("location_admin", loc_admin_user, scope_root),
            ("employee", employee_user, None),
        ]

        for role_code, user, location in role_assignments:
            try:
                role = Role.objects.get(code=role_code)
            except Role.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"  [SKIP] Role '{role_code}' not found — run seed_roles_permissions first."
                ))
                continue

            exists = UserRoleAssignment.objects.filter(
                user=user, role=role, is_active=True,
            ).exists()
            if not exists:
                UserRoleAssignment.objects.create(
                    user=user, role=role, location=location,
                    is_primary=True, is_active=True,
                )
                scope_label = f" @ {location.name}" if location else " (global)"
                self.stdout.write(self.style.SUCCESS(
                    f"  [ASSIGNED] {user.email} -> {role_code}{scope_label}"
                ))
            else:
                self.stdout.write(f"  [EXISTS] {user.email} -> {role_code}")

        # ==================================================================
        # 4. Assets
        # ==================================================================
        self.stdout.write("Seeding demo assets...")

        category = AssetCategory.objects.filter(is_active=True).first()
        demo_assets = []

        if asset_location and category:
            for i, (aid, name) in enumerate([
                ("DEMO-AST-001", "Demo Laptop #1"),
                ("DEMO-AST-002", "Demo Monitor #2"),
                ("DEMO-AST-003", "Demo Desk Chair #3"),
            ], start=1):
                asset, created = Asset.objects.get_or_create(
                    asset_id=aid,
                    defaults={
                        "name": name,
                        "category": category,
                        "current_location": asset_location,
                        "created_by": admin_user,
                        "serial_number": f"SN-DEMO-{i:04d}",
                        "status": Asset.Status.ACTIVE,
                    },
                )
                demo_assets.append(asset)
                self._log(created, aid)

            first_asset = demo_assets[0]
            has_assignment = AssetAssignment.objects.filter(
                asset=first_asset, end_at__isnull=True,
            ).exists()
            if not has_assignment:
                assign_asset(
                    first_asset, employee_user, timezone.now(),
                    assigned_by=admin_user, note="Demo seed assignment",
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  [ASSIGNED] {first_asset.asset_id} -> employee@demo.local (with AssetAssignment)"
                ))
            else:
                self.stdout.write(f"  [EXISTS] Assignment for {first_asset.asset_id}")
        else:
            self.stdout.write(self.style.WARNING(
                "  [SKIP] No location or category — run location/asset seed commands first."
            ))

        # ==================================================================
        # 5. Verification cycle + request with asset snapshots
        # ==================================================================
        self.stdout.write("Seeding demo verification cycle...")

        today = date.today()
        cycle, created = VerificationCycle.objects.get_or_create(
            code="DEMO-CYCLE-01",
            defaults={
                "name": "Demo Verification Cycle",
                "start_date": today,
                "end_date": today + timedelta(days=30),
                "status": VerificationCycle.Status.ACTIVE,
                "created_by": admin_user,
            },
        )
        self._log(created, "DEMO-CYCLE-01")

        active_vr = VerificationRequest.objects.filter(
            cycle=cycle, employee=employee_user,
            status__in=VerificationRequest.ACTIVE_STATUSES,
        ).first()

        if not active_vr:
            import secrets

            ref_code = f"VER-DEMO-{secrets.token_hex(3).upper()}"
            try:
                vr = create_verification_request(
                    cycle=cycle,
                    employee=employee_user,
                    requested_by=admin_user,
                    location_scope=scope_root,
                    reference_code=ref_code,
                )
                vr.sent_at = timezone.now()
                vr.save(update_fields=["sent_at", "updated_at"])

                if demo_assets:
                    asset_qs = Asset.objects.filter(
                        pk__in=[a.pk for a in demo_assets],
                    ).select_related("category", "current_location")
                    snapshots = snapshot_request_assets(vr, asset_qs)
                    self.stdout.write(self.style.SUCCESS(
                        f"  [CREATED] Verification request {ref_code} with {len(snapshots)} asset snapshots"
                    ))
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f"  [CREATED] Verification request {ref_code} (no assets to snapshot)"
                    ))
            except ValueError as exc:
                self.stdout.write(self.style.WARNING(f"  [SKIP] {exc}"))
        else:
            self.stdout.write("  [EXISTS] Active verification request for employee")
            has_snapshots = active_vr.request_assets.exists()
            if not has_snapshots and demo_assets:
                asset_qs = Asset.objects.filter(
                    pk__in=[a.pk for a in demo_assets],
                ).select_related("category", "current_location")
                snapshots = snapshot_request_assets(active_vr, asset_qs)
                self.stdout.write(self.style.SUCCESS(
                    f"  [ADDED] {len(snapshots)} asset snapshots to existing request"
                ))

        # ==================================================================
        # 6. Pending field submission
        # ==================================================================
        self.stdout.write("Seeding demo field submission...")

        if asset_location:
            existing_sub = FieldSubmission.objects.filter(
                submitted_by=tp_user,
                submission_type=FieldSubmission.SubmissionType.NEW_ASSET_CANDIDATE,
                status=FieldSubmission.Status.PENDING,
                asset_name="Unregistered Projector",
            ).exists()

            if not existing_sub:
                FieldSubmission.objects.create(
                    submitted_by=tp_user,
                    submission_type=FieldSubmission.SubmissionType.NEW_ASSET_CANDIDATE,
                    location=asset_location,
                    location_snapshot={
                        "id": str(asset_location.pk),
                        "code": asset_location.code,
                        "name": asset_location.name,
                    },
                    asset_name="Unregistered Projector",
                    serial_number="PROJ-XYZ-999",
                    asset_type_name="Electronics",
                    remarks="Found in conference room B, not tagged.",
                    status=FieldSubmission.Status.PENDING,
                    submitted_at=timezone.now(),
                )
                self.stdout.write(self.style.SUCCESS(
                    "  [CREATED] Pending submission: Unregistered Projector"
                ))
            else:
                self.stdout.write("  [EXISTS] Pending submission: Unregistered Projector")
        else:
            self.stdout.write(self.style.WARNING(
                "  [SKIP] No location available for submission."
            ))

        # ==================================================================
        # Summary
        # ==================================================================
        self.stdout.write(self.style.SUCCESS(
            "\nDemo data seeding complete. "
            "Users: admin@demo.local, locadmin@demo.local, "
            "employee@demo.local, thirdparty@demo.local"
        ))

    def _log(self, created, label):
        if created:
            self.stdout.write(self.style.SUCCESS(f"  [CREATED] {label}"))
        else:
            self.stdout.write(f"  [EXISTS] {label}")
