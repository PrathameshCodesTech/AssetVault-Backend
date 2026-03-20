"""
Management command to seed roles, permissions, and role-permission mappings.

This command is idempotent — safe to run multiple times. It uses get_or_create
and update_or_create so existing data is never duplicated.
"""
from django.core.management.base import BaseCommand

from access.models import Permission, PermissionTemplate, PermissionTemplatePermission, Role, RolePermission


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
    {
        "code": "vendor",
        "name": "Vendor",
        "description": "Respond to assigned vendor verification requests",
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
    # module: reports
    {"code": "report.view",     "name": "View Reports",      "module": "reports"},
    # module: dashboard
    {"code": "dashboard.view",  "name": "View Dashboard",    "module": "dashboard"},
    # module: users
    {"code": "user.manage",  "name": "Manage Users",         "module": "users"},
    {"code": "role.manage",  "name": "Manage Roles",         "module": "users"},
    # module: vendors
    {"code": "vendor.manage",  "name": "Manage Vendor Organizations", "module": "vendors"},
    {"code": "vendor.request", "name": "Create/View Vendor Requests", "module": "vendors"},
    {"code": "vendor.respond", "name": "Respond to Vendor Requests",  "module": "vendors"},
]

PERMISSION_TEMPLATES = [
    {
        "code": "super_admin_template",
        "name": "Super Admin",
        "description": "Full system access — all permissions.",
        "sort_order": 10,
    },
    {
        "code": "location_admin_template",
        "name": "Location Admin",
        "description": "Manage assets and verification within assigned locations.",
        "sort_order": 20,
    },
    {
        "code": "employee_template",
        "name": "Employee",
        "description": "Verify assigned assets and view dashboard.",
        "sort_order": 30,
    },
    {
        "code": "asset_operations_template",
        "name": "Asset Operations",
        "description": "Full asset management including import and assignment.",
        "sort_order": 40,
    },
    {
        "code": "vendor_template",
        "name": "Vendor",
        "description": "Respond to vendor verification requests, view assigned assets, upload photos.",
        "sort_order": 50,
    },
]

# Maps template code → list of permission codes included in that template
TEMPLATE_PERMISSION_MAP: dict[str, list[str]] = {
    "super_admin_template": [p["code"] for p in PERMISSIONS],
    "location_admin_template": [
        "asset.view",
        "asset.create",
        "asset.update",
        "asset.assign",
        "asset.import",
        "location.view",
        "verification.request",
        "vendor.request",
        "report.view",
        "dashboard.view",
    ],
    "employee_template": [
        "asset.view",
        "verification.respond",
        "dashboard.view",
    ],
    "asset_operations_template": [
        "asset.view",
        "asset.create",
        "asset.update",
        "asset.assign",
        "asset.import",
        "location.view",
    ],
    "vendor_template": [
        "asset.view",
        "location.view",
        "vendor.respond",
        "dashboard.view",
    ],
}

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
        "vendor.request",
        "report.view",
        "dashboard.view",
    ],
    "employee": [
        "asset.view",
        "verification.respond",
        "dashboard.view",
    ],
    "vendor": [
        "asset.view",
        "location.view",
        "vendor.respond",
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
        # Upsert permission templates
        # ----------------------------------------------------------------
        self.stdout.write("Seeding permission templates...")
        templates_created = 0
        templates_updated = 0
        template_mappings_created = 0
        template_cache: dict[str, PermissionTemplate] = {}

        for tmpl_data in PERMISSION_TEMPLATES:
            obj, created = PermissionTemplate.objects.update_or_create(
                code=tmpl_data["code"],
                defaults={
                    "name": tmpl_data["name"],
                    "description": tmpl_data["description"],
                    "sort_order": tmpl_data["sort_order"],
                },
            )
            template_cache[obj.code] = obj
            if created:
                templates_created += 1
                self.stdout.write(self.style.SUCCESS(f"  [CREATED] Template: {obj.code}"))
            else:
                templates_updated += 1
                self.stdout.write(self.style.WARNING(f"  [UPDATED] Template: {obj.code}"))

        # ----------------------------------------------------------------
        # Map permissions to templates
        # ----------------------------------------------------------------
        self.stdout.write("Mapping permissions to templates...")
        for tmpl_code, perm_codes in TEMPLATE_PERMISSION_MAP.items():
            tmpl = template_cache.get(tmpl_code)
            if tmpl is None:
                self.stdout.write(self.style.ERROR(f"  [SKIP] Template '{tmpl_code}' not found."))
                continue
            for perm_code in perm_codes:
                perm = perm_cache.get(perm_code)
                if perm is None:
                    self.stdout.write(self.style.ERROR(f"  [SKIP] Permission '{perm_code}' not found."))
                    continue
                _, created = PermissionTemplatePermission.objects.get_or_create(
                    template=tmpl, permission=perm
                )
                if created:
                    template_mappings_created += 1

        # ----------------------------------------------------------------
        # Summary
        # ----------------------------------------------------------------
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created {roles_created} roles, updated {roles_updated} roles, "
                f"created {perms_created} permissions, updated {perms_updated} permissions, "
                f"mapped {mappings_created} role-permissions. "
                f"Created {templates_created} templates, updated {templates_updated} templates, "
                f"mapped {template_mappings_created} template-permissions."
            )
        )
