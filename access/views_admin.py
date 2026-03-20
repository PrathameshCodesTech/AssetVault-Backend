"""
Superadmin views for RBAC management: Roles, Permissions, UserRoleAssignments.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.models import Permission, PermissionTemplate, PermissionTemplatePermission, Role, RolePermission, UserRoleAssignment
from access.permissions import IsSuperAdmin
from access.serializers_admin import (
    PermissionSerializer,
    PermissionTemplateSerializer,
    RoleDetailSerializer,
    RoleSerializer,
    UserRoleAssignmentSerializer,
)


class AdminRoleListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        roles = Role.objects.prefetch_related("role_permissions").all()
        serializer = RoleSerializer(roles, many=True)
        return Response(serializer.data)

    def post(self, request):
        code = request.data.get("code", "").strip()
        name = request.data.get("name", "").strip()
        template_id = request.data.get("template_id")

        errors = {}
        if not code:
            errors["code"] = ["This field is required."]
        elif Role.objects.filter(code=code).exists():
            errors["code"] = ["A role with this code already exists."]
        if not name:
            errors["name"] = ["This field is required."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        role = Role.objects.create(
            code=code,
            name=name,
            description=request.data.get("description", ""),
            is_active=request.data.get("is_active", True),
        )

        if template_id:
            template = PermissionTemplate.objects.filter(pk=template_id, is_active=True).first()
            if template is None:
                role.delete()
                return Response(
                    {"template_id": ["Template not found or inactive."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            perm_ids = PermissionTemplatePermission.objects.filter(template=template).values_list(
                "permission_id", flat=True
            )
            for perm_id in perm_ids:
                RolePermission.objects.get_or_create(role=role, permission_id=perm_id)

        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)


class AdminRoleDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        return Response(RoleDetailSerializer(role).data)

    def patch(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        allowed_fields = {"name", "description", "is_active"}
        for field in allowed_fields:
            if field in request.data:
                setattr(role, field, request.data[field])
        role.save()
        return Response(RoleDetailSerializer(role).data)


class AdminRolePermissionsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        perms = Permission.objects.filter(role_permissions__role=role)
        serializer = PermissionSerializer(perms, many=True)
        return Response(serializer.data)

    def post(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        permission_id = request.data.get("permission_id")
        if not permission_id:
            return Response({"permission_id": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
        permission = get_object_or_404(Permission, pk=permission_id)
        if RolePermission.objects.filter(role=role, permission=permission).exists():
            return Response(
                {"detail": "This permission is already assigned to this role."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        RolePermission.objects.create(role=role, permission=permission)
        return Response({"detail": "Permission assigned."}, status=status.HTTP_201_CREATED)


class AdminRolePermissionRemoveView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def delete(self, request, pk, perm_id):
        role = get_object_or_404(Role, pk=pk)
        rp = get_object_or_404(RolePermission, role=role, permission_id=perm_id)
        rp.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminPermissionListView(APIView):
    """Read-only catalog of all platform-defined permissions."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = Permission.objects.all()
        module = request.query_params.get("module")
        if module:
            qs = qs.filter(module=module)
        return Response(PermissionSerializer(qs, many=True).data)


class AdminPermissionDetailView(APIView):
    """Read-only detail of a single permission."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        perm = get_object_or_404(Permission, pk=pk)
        return Response(PermissionSerializer(perm).data)


class AdminPermissionTemplateListView(APIView):
    """List all active permission templates with their permissions."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = PermissionTemplate.objects.filter(is_active=True)
        return Response(PermissionTemplateSerializer(qs, many=True).data)


class AdminPermissionTemplateDetailView(APIView):
    """Detail of a single permission template."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        tmpl = get_object_or_404(PermissionTemplate, pk=pk, is_active=True)
        return Response(PermissionTemplateSerializer(tmpl).data)


class AdminApplyTemplateView(APIView):
    """Replace a role's permission set with those from a template."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        template_id = request.data.get("template_id")
        if not template_id:
            return Response({"template_id": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

        template = get_object_or_404(PermissionTemplate, pk=template_id, is_active=True)

        # Replace all existing role permissions with template's set
        perm_ids = list(
            PermissionTemplatePermission.objects.filter(template=template).values_list(
                "permission_id", flat=True
            )
        )
        RolePermission.objects.filter(role=role).delete()
        RolePermission.objects.bulk_create(
            [RolePermission(role=role, permission_id=pid) for pid in perm_ids],
            ignore_conflicts=True,
        )

        return Response(RoleDetailSerializer(role).data)


class AdminUserRoleAssignmentListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = UserRoleAssignment.objects.select_related("user", "role", "location").all()
        user_id = request.query_params.get("user_id")
        role_id = request.query_params.get("role_id")
        if user_id:
            qs = qs.filter(user_id=user_id)
        if role_id:
            qs = qs.filter(role_id=role_id)
        serializer = UserRoleAssignmentSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        from django.shortcuts import get_object_or_404
        from accounts.models import User
        from access.models import Role
        from locations.models import LocationNode

        errors = {}
        user_id = request.data.get("user_id")
        role_id = request.data.get("role_id")

        if not user_id:
            errors["user_id"] = ["This field is required."]
        if not role_id:
            errors["role_id"] = ["This field is required."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        user = get_object_or_404(User, pk=user_id)
        role = get_object_or_404(Role, pk=role_id)

        location = None
        location_id = request.data.get("location_id")
        if location_id:
            location = get_object_or_404(LocationNode, pk=location_id)

        assignment = UserRoleAssignment(
            user=user,
            role=role,
            location=location,
            is_primary=request.data.get("is_primary", False),
            starts_at=request.data.get("starts_at"),
            ends_at=request.data.get("ends_at"),
            is_active=request.data.get("is_active", True),
        )
        try:
            assignment.full_clean()
            assignment.save()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            UserRoleAssignmentSerializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )


class AdminUserRoleAssignmentDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        assignment = get_object_or_404(
            UserRoleAssignment.objects.select_related("user", "role", "location"), pk=pk
        )
        return Response(UserRoleAssignmentSerializer(assignment).data)

    def patch(self, request, pk):
        assignment = get_object_or_404(
            UserRoleAssignment.objects.select_related("user", "role", "location"), pk=pk
        )
        allowed_fields = {"is_primary", "is_active", "starts_at", "ends_at"}
        for field in allowed_fields:
            if field in request.data:
                setattr(assignment, field, request.data[field])

        location_id = request.data.get("location_id")
        if location_id is not None:
            if location_id == "" or location_id is None:
                assignment.location = None
            else:
                from locations.models import LocationNode
                assignment.location = get_object_or_404(LocationNode, pk=location_id)

        try:
            assignment.full_clean()
            assignment.save()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(UserRoleAssignmentSerializer(assignment).data)

    def delete(self, request, pk):
        assignment = get_object_or_404(UserRoleAssignment, pk=pk)
        assignment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
