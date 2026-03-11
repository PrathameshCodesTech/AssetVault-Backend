from django.contrib import admin

from .models import Permission, Role, RolePermission, UserRoleAssignment


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "created_at")
    search_fields = ("code", "name")


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "module", "is_active")
    list_filter = ("module",)
    search_fields = ("code", "name")


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ("role", "permission")
    list_filter = ("role",)


@admin.register(UserRoleAssignment)
class UserRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "location", "is_primary", "is_active", "starts_at", "ends_at")
    list_filter = ("role", "is_active")
    search_fields = ("user__email",)
