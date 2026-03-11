from rest_framework import serializers

from accounts.models import User
from access.helpers import (
    get_primary_role,
    get_user_permission_codes,
    get_user_scope,
)
from access.models import UserRoleAssignment


class SendOtpSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyOtpSerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=10)


class RoleAssignmentSerializer(serializers.ModelSerializer):
    role_code = serializers.CharField(source="role.code", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    location_id = serializers.UUIDField(source="location.id", read_only=True, default=None)
    location_name = serializers.SerializerMethodField()

    class Meta:
        model = UserRoleAssignment
        fields = [
            "id",
            "role_code",
            "role_name",
            "location_id",
            "location_name",
            "is_primary",
            "is_active",
        ]

    def get_location_name(self, obj):
        return obj.location.name if obj.location_id else None


class UserOptionSerializer(serializers.ModelSerializer):
    """Slim user payload for employee-selection dropdowns (id / email / name only)."""

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name"]

    def get_name(self, obj):
        return obj.get_full_name()


class UserSerializer(serializers.ModelSerializer):
    """Full user payload for /me with RBAC data."""

    name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    role_codes = serializers.SerializerMethodField()
    permission_codes = serializers.SerializerMethodField()
    locationId = serializers.SerializerMethodField()
    locationName = serializers.SerializerMethodField()
    assignedLocationIds = serializers.SerializerMethodField()
    role_assignments = serializers.SerializerMethodField()
    is_global_scope = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "role",
            "role_codes",
            "permission_codes",
            "locationId",
            "locationName",
            "assignedLocationIds",
            "role_assignments",
            "is_global_scope",
        ]

    def get_name(self, obj):
        return obj.get_full_name()

    def get_role(self, obj):
        role = get_primary_role(obj)
        return role.code if role else None

    def get_role_codes(self, obj):
        scope = self._get_scope(obj)
        return list(scope["role_codes"])

    def get_permission_codes(self, obj):
        return list(get_user_permission_codes(obj))

    def get_locationId(self, obj):
        assignments = UserRoleAssignment.objects.filter(
            user=obj, is_active=True, is_primary=True
        ).select_related("location").first()
        if assignments and assignments.location_id:
            return str(assignments.location_id)
        return None

    def get_locationName(self, obj):
        assignments = UserRoleAssignment.objects.filter(
            user=obj, is_active=True, is_primary=True
        ).select_related("location").first()
        if assignments and assignments.location_id:
            return assignments.location.name
        return None

    def get_assignedLocationIds(self, obj):
        ids = list(
            UserRoleAssignment.objects.filter(user=obj, is_active=True)
            .exclude(location=None)
            .values_list("location_id", flat=True)
        )
        return [str(i) for i in ids]

    def get_role_assignments(self, obj):
        qs = UserRoleAssignment.objects.filter(
            user=obj, is_active=True
        ).select_related("role", "location")
        return RoleAssignmentSerializer(qs, many=True).data

    def get_is_global_scope(self, obj):
        scope = self._get_scope(obj)
        return scope["is_global"]

    def _get_scope(self, obj):
        cache_key = "_scope_cache"
        if not hasattr(obj, cache_key):
            setattr(obj, cache_key, get_user_scope(obj))
        return getattr(obj, cache_key)
