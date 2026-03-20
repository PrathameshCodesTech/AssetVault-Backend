"""
Serializers for superadmin user management APIs.
"""
from rest_framework import serializers

from accounts.models import User


class AdminUserListSerializer(serializers.ModelSerializer):
    role_summary = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "employee_code",
            "phone",
            "is_active",
            "date_joined",
            "role_summary",
        ]
        read_only_fields = ["id", "date_joined", "role_summary"]

    def get_role_summary(self, obj):
        assignments = obj.role_assignments.filter(is_active=True).select_related("role")
        return [
            {
                "role_code": a.role.code,
                "role_name": a.role.name,
                "is_primary": a.is_primary,
            }
            for a in assignments
        ]


class AdminUserDetailSerializer(AdminUserListSerializer):
    assignments = serializers.SerializerMethodField(read_only=True)

    class Meta(AdminUserListSerializer.Meta):
        fields = AdminUserListSerializer.Meta.fields + ["assignments"]
        read_only_fields = AdminUserListSerializer.Meta.read_only_fields + ["assignments"]

    def get_assignments(self, obj):
        from access.serializers_admin import UserRoleAssignmentSerializer
        assignments = obj.role_assignments.select_related("user", "role", "location").all()
        return UserRoleAssignmentSerializer(assignments, many=True).data


class AdminUserCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "email",
            "first_name",
            "last_name",
            "employee_code",
            "phone",
            "is_active",
        ]

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "employee_code",
            "phone",
            "is_active",
        ]
