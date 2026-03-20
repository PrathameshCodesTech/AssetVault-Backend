"""
Serializers for superadmin RBAC management APIs.
"""
from rest_framework import serializers

from access.models import Permission, PermissionTemplate, Role, RolePermission, UserRoleAssignment


class PermissionTemplateSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PermissionTemplate
        fields = ["id", "code", "name", "description", "is_active", "sort_order", "permissions"]

    def get_permissions(self, obj):
        perms = (
            Permission.objects.filter(template_permissions__template=obj)
            .values("id", "code", "name", "module")
        )
        return list(perms)


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "code", "name", "module", "description", "is_active"]
        read_only_fields = ["id"]


class RoleSerializer(serializers.ModelSerializer):
    permission_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Role
        fields = ["id", "code", "name", "description", "is_active", "created_at", "updated_at", "permission_count"]
        read_only_fields = ["id", "created_at", "updated_at", "permission_count"]

    def get_permission_count(self, obj):
        return obj.role_permissions.count()


class RoleDetailSerializer(RoleSerializer):
    permissions = serializers.SerializerMethodField(read_only=True)

    class Meta(RoleSerializer.Meta):
        fields = RoleSerializer.Meta.fields + ["permissions"]
        read_only_fields = RoleSerializer.Meta.read_only_fields + ["permissions"]

    def get_permissions(self, obj):
        perms = (
            Permission.objects.filter(role_permissions__role=obj)
            .values("id", "code", "name", "module")
        )
        return list(perms)


class UserRoleAssignmentSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.SerializerMethodField(read_only=True)
    role_code = serializers.CharField(source="role.code", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    location_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = UserRoleAssignment
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_name",
            "role_id",
            "role_code",
            "role_name",
            "location_id",
            "location_name",
            "is_primary",
            "starts_at",
            "ends_at",
            "is_active",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "user_email",
            "user_name",
            "role_code",
            "role_name",
            "location_name",
            "created_at",
        ]

    def get_user_name(self, obj):
        return obj.user.get_full_name()

    def get_location_name(self, obj):
        if obj.location_id:
            return obj.location.name
        return None
