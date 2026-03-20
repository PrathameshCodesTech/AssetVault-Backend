"""
Superadmin views for verification cycle management.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.permissions import IsSuperAdmin
from verification.models import VerificationCycle
from verification.serializers_admin import (
    AdminVerificationCycleCreateSerializer,
    AdminVerificationCycleSerializer,
)


class AdminCycleListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = VerificationCycle.objects.select_related("created_by").all()
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response(AdminVerificationCycleSerializer(qs, many=True).data)

    def post(self, request):
        serializer = AdminVerificationCycleCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            cycle = VerificationCycle.objects.create(
                name=data["name"],
                code=data["code"],
                description=data.get("description", ""),
                start_date=data["start_date"],
                end_date=data["end_date"],
                status=VerificationCycle.Status.DRAFT,
                created_by=request.user,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            AdminVerificationCycleSerializer(cycle).data,
            status=status.HTTP_201_CREATED,
        )


class AdminCycleDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        cycle = get_object_or_404(VerificationCycle.objects.select_related("created_by"), pk=pk)
        return Response(AdminVerificationCycleSerializer(cycle).data)

    def patch(self, request, pk):
        cycle = get_object_or_404(VerificationCycle.objects.select_related("created_by"), pk=pk)
        if cycle.status == VerificationCycle.Status.CLOSED:
            return Response(
                {"detail": "Cannot update a closed verification cycle."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        for field in ("name", "description", "start_date", "end_date"):
            if field in request.data:
                setattr(cycle, field, request.data[field])
        try:
            cycle.save()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        cycle.refresh_from_db()
        return Response(AdminVerificationCycleSerializer(cycle).data)


class AdminCycleActivateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request, pk):
        cycle = get_object_or_404(VerificationCycle, pk=pk)
        if cycle.status != VerificationCycle.Status.DRAFT:
            return Response(
                {"detail": "Only DRAFT cycles can be activated."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Enforce one active cycle at a time — quick-send picks the first active
        # cycle and would be ambiguous if multiple are active simultaneously.
        already_active = VerificationCycle.objects.filter(
            status=VerificationCycle.Status.ACTIVE
        ).exclude(pk=pk).first()
        if already_active:
            return Response(
                {
                    "detail": (
                        f"Cycle '{already_active.name}' is already active. "
                        "Close it before activating a new one."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        cycle.status = VerificationCycle.Status.ACTIVE
        try:
            cycle.save()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        cycle.refresh_from_db()
        return Response(AdminVerificationCycleSerializer(cycle).data)


class AdminCycleCloseView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request, pk):
        cycle = get_object_or_404(VerificationCycle, pk=pk)
        if cycle.status != VerificationCycle.Status.ACTIVE:
            return Response(
                {"detail": "Only ACTIVE cycles can be closed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cycle.status = VerificationCycle.Status.CLOSED
        try:
            cycle.save()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        cycle.refresh_from_db()
        return Response(AdminVerificationCycleSerializer(cycle).data)
