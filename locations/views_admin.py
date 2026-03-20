"""
Superadmin views for location hierarchy management.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.permissions import IsSuperAdmin
from locations.models import LocationClosure, LocationNode, LocationType
from locations.serializers_admin import (
    AdminLocationNodeCreateSerializer,
    AdminLocationNodeSerializer,
    LocationTypeSerializer,
)


class AdminLocationTypeListView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = LocationType.objects.all()
        return Response(LocationTypeSerializer(qs, many=True).data)


class AdminLocationNodeListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = LocationNode.objects.select_related("location_type", "parent").all()

        location_type = request.query_params.get("location_type")
        if location_type:
            qs = qs.filter(location_type__code=location_type)

        parent_id = request.query_params.get("parent_id")
        if parent_id:
            qs = qs.filter(parent_id=parent_id)

        is_active = request.query_params.get("is_active")
        if is_active is not None:
            active_val = is_active.lower() in ("true", "1", "yes")
            qs = qs.filter(is_active=active_val)

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))

        return Response(AdminLocationNodeSerializer(qs, many=True).data)

    def post(self, request):
        serializer = AdminLocationNodeCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        location_type = data["_location_type"]
        parent = data["_parent"]
        code = data["code"]
        name = data["name"]

        node = LocationNode(
            location_type=location_type,
            parent=parent,
            code=code,
            name=name,
        )

        try:
            node.save()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        node.refresh_from_db()
        return Response(
            AdminLocationNodeSerializer(node).data,
            status=status.HTTP_201_CREATED,
        )


class AdminLocationNodeDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        node = get_object_or_404(
            LocationNode.objects.select_related("location_type", "parent"), pk=pk
        )
        return Response(AdminLocationNodeSerializer(node).data)

    def patch(self, request, pk):
        node = get_object_or_404(
            LocationNode.objects.select_related("location_type", "parent"), pk=pk
        )
        for field in ("name", "is_active"):
            if field in request.data:
                setattr(node, field, request.data[field])

        try:
            node.save()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        node.refresh_from_db()
        return Response(AdminLocationNodeSerializer(node).data)
