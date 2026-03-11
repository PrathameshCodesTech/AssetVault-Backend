"""
Management command to seed roles, permissions, and role-permission mappings.

This command is idempotent — safe to run multiple times. It uses get_or_create
and update_or_create so existing data is never duplicated.
"""
from django.core.management.base import BaseCommand

from access.models import Permission, Role, RolePermission


# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

ROLES = [
    {
        "code": "super_admin",
        "name": "Super Admin",
        "description": "Full system access",
    },
    {
        "code": "location_admin",
        "name": "Location Admin",
        "description": "Manage assets and verification within assigned locations",
    },
    {
        "code": "employee",
        "name": "Employee",
        "description": "Verify assigned assets",
    },
]

PERMISSIONS = [
    # module: assets
    {"code": "asset.view",   "name": "View Assets",          "module": "assets"},
    {"code": "asset.create", "name": "Create Assets",        "module": "assets"},
    {"code": "asset.update", "name": "Update Assets",        "module": "assets"},
    {"code": "asset.assign", "name": "Assign Assets",        "module": "assets"},
    {"code": "asset.import", "name": "Import Assets",        "module": "assets"},
    # module: locations
    {"code": "location.view", "name": "View Locations",      "module": "locations"},
    # module: verification
    {"code": "verification.request", "name": "Request Verification", "module": "verification"},
    {"code": "verification.respond", "name": "Respond to Verification", "module": "verification"},
    # module: submissions
    {"code": "submission.create", "name": "Create Submission", "module": "submissions"},
    {"code": "submission.review", "name": "Review Submissions", "module": "submissions"},
    # module: reports
    {"code": "report.view",     "name": "View Reports",      "module": "reports"},
    # module: dashboard
    {"code": "dashboard.view",  "name": "View Dashboard",    "module": "dashboard"},
    # module: users
    {"code": "user.manage",  "name": "Manage Users",         "module": "users"},
    {"code": "role.manage",  "name": "Manage Roles",         "module": "users"},
]

# Maps role code → list of permission codes assigned to that role
ROLE_PERMISSION_MAP = {
    "super_admin": [p["code"] for p in PERMISSIONS],  # all permissions
    "location_admin": [
        "asset.view",
        "asset.create",
        "asset.update",
        "asset.assign",
        "asset.import",
        "location.view",
        "verification.request",
        "submission.review",
        "report.view",
        "dashboard.view",
    ],
    "employee": [
        "asset.view",
        "verification.respond",
        "dashboard.view",
    ],
}


class Command(BaseCommand):
    help = "Seed roles, permissions, and role-permission mappings (idempotent)."

    def handle(self, *args, **options):
        roles_created = 0
        roles_updated = 0
        perms_created = 0
        perms_updated = 0
        mappings_created = 0

        # ----------------------------------------------------------------
        # Upsert roles
        # ----------------------------------------------------------------
        self.stdout.write("Seeding roles...")
        for role_data in ROLES:
            obj, created = Role.objects.update_or_create(
                code=role_data["code"],
                defaults={
                    "name": role_data["name"],
                    "description": role_data["description"],
                },
            )
            if created:
                roles_created += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  [CREATED] Role: {obj.code}")
                )
            else:
                roles_updated += 1
                self.stdout.write(
                    self.style.WARNING(f"  [UPDATED] Role: {obj.code}")
                )

        # ----------------------------------------------------------------
        # Upsert permissions
        # ----------------------------------------------------------------
        self.stdout.write("Seeding permissions...")
        perm_cache: dict[str, Permission] = {}
        for perm_data in PERMISSIONS:
            obj, created = Permission.objects.update_or_create(
                code=perm_data["code"],
                defaults={
                    "name": perm_data["name"],
                    "module": perm_data["module"],
                },
            )
            perm_cache[obj.code] = obj
            if created:
                perms_created += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  [CREATED] Permission: {obj.code}")
                )
            else:
                perms_updated += 1
                self.stdout.write(
                    self.style.WARNING(f"  [UPDATED] Permission: {obj.code}")
                )

        # ----------------------------------------------------------------
        # Map permissions to roles
        # ----------------------------------------------------------------
        self.stdout.write("Mapping permissions to roles...")
        for role_code, perm_codes in ROLE_PERMISSION_MAP.items():
            try:
                role = Role.objects.get(code=role_code)
            except Role.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(
                        f"  [SKIP] Role '{role_code}' not found — skipping mappings."
                    )
                )
                continue

            for perm_code in perm_codes:
                perm = perm_cache.get(perm_code)
                if perm is None:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  [SKIP] Permission '{perm_code}' not found — skipping."
                        )
                    )
                    continue

                _, created = RolePermission.objects.get_or_create(
                    role=role, permission=perm
                )
                if created:
                    mappings_created += 1

        # ----------------------------------------------------------------
        # Summary
        # ----------------------------------------------------------------
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created {roles_created} roles, updated {roles_updated} roles, "
                f"created {perms_created} permissions, updated {perms_updated} permissions, "
                f"mapped {mappings_created} role-permissions."
            )
        )
