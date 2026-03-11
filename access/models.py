import uuid
from django.core.exceptions import ValidationError
from django.db import models


class Role(models.Model):
    """A named role that can carry one or more permissions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "access_role"
        ordering = ("name",)

    def __str__(self):
        return self.name


class Permission(models.Model):
    """A discrete action that can be granted to a role."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=150, unique=True)
    name = models.CharField(max_length=200)
    module = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "access_permission"
        ordering = ("module", "name")

    def __str__(self):
        return f"{self.module}.{self.code}"


class RolePermission(models.Model):
    """Maps a permission to a role."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="role_permissions")

    class Meta:
        db_table = "access_role_permission"
        unique_together = (("role", "permission"),)

    def __str__(self):
        return f"{self.role.code} -> {self.permission.code}"


class UserRoleAssignment(models.Model):
    """Assigns a role to a user, optionally scoped to a location node."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="user_assignments",
    )
    # Optional: scope this assignment to a specific location subtree.
    # PROTECT is intentional — if the scoped location is deleted, the assignment must be
    # explicitly resolved first. SET_NULL would silently widen a scoped role into a
    # global one, which is a security regression.
    location = models.ForeignKey(
        "locations.LocationNode",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    is_primary = models.BooleanField(default=False)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "access_user_role_assignment"
        indexes = [
            models.Index(fields=["user"], name="access_ura_user_idx"),
            models.Index(fields=["role"], name="access_ura_role_idx"),
            models.Index(fields=["is_active"], name="access_ura_is_active_idx"),
        ]

    def clean(self):
        # ends_at must come after starts_at
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError("ends_at must be later than starts_at.")

        # Only one active primary role assignment per user.
        # is_primary is meant to identify the user's main/default role.
        if self.is_primary and self.is_active and self.user_id:
            qs = UserRoleAssignment.objects.filter(
                user_id=self.user_id, is_primary=True, is_active=True
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    "This user already has an active primary role assignment. "
                    "Deactivate it before assigning a new primary role."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        loc = f" @ {self.location_id}" if self.location_id else ""
        return f"{self.user.email} -> {self.role.code}{loc}"
