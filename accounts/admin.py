from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import OtpChallenge, OutboundEmail, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "employee_code", "is_active", "is_staff", "date_joined")
    search_fields = ("email", "first_name", "last_name", "employee_code")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "display_name", "employee_code", "phone")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2"),
        }),
    )


@admin.register(OtpChallenge)
class OtpChallengeAdmin(admin.ModelAdmin):
    list_display = ("email", "purpose", "expires_at", "consumed_at", "attempt_count", "created_at")
    list_filter = ("purpose",)
    search_fields = ("email",)
    readonly_fields = ("code_hash",)


@admin.register(OutboundEmail)
class OutboundEmailAdmin(admin.ModelAdmin):
    list_display = ("to_email", "subject", "status", "sent_at", "created_at")
    list_filter = ("status",)
    search_fields = ("to_email", "subject")
