"""
Superadmin views for user management.
"""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.permissions import IsSuperAdmin
from accounts.models import User
from accounts.serializers_admin import (
    AdminUserCreateSerializer,
    AdminUserDetailSerializer,
    AdminUserListSerializer,
    AdminUserUpdateSerializer,
)


class AdminUserListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = User.objects.all().order_by("date_joined")

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        is_active = request.query_params.get("is_active")
        if is_active is not None:
            active_val = is_active.lower() in ("true", "1", "yes")
            qs = qs.filter(is_active=active_val)

        serializer = AdminUserListSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = AdminUserCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        user = User.objects.create_user(
            email=validated["email"],
            password=None,
            first_name=validated.get("first_name", ""),
            last_name=validated.get("last_name", ""),
            employee_code=validated.get("employee_code"),
            phone=validated.get("phone"),
            is_active=validated.get("is_active", True),
        )
        user.set_unusable_password()
        user.save()
        return Response(AdminUserDetailSerializer(user).data, status=status.HTTP_201_CREATED)


class AdminUserDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return Response(AdminUserDetailSerializer(user).data)

    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(AdminUserDetailSerializer(user).data)


class AdminUserAssignmentsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        from access.models import UserRoleAssignment
        from access.serializers_admin import UserRoleAssignmentSerializer
        assignments = UserRoleAssignment.objects.filter(user=user).select_related(
            "user", "role", "location"
        )
        serializer = UserRoleAssignmentSerializer(assignments, many=True)
        return Response(serializer.data)
