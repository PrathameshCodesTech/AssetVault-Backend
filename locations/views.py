from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.permissions import permission_required
from locations.models import LocationNode, LocationType
from locations.serializers import (
    LocationNodeSerializer,
    LocationTypeSerializer,
    build_location_tree,
)


class LocationTypeListView(ListAPIView):
    """GET /api/locations/types — list all location types."""

    permission_classes = [IsAuthenticated, permission_required("location.view")]
    serializer_class = LocationTypeSerializer
    queryset = LocationType.objects.filter(is_active=True)
    pagination_class = None


class LocationNodeListView(ListAPIView):
    """GET /api/locations/nodes — list location nodes with optional filters."""

    permission_classes = [IsAuthenticated, permission_required("location.view")]
    serializer_class = LocationNodeSerializer

    def get_queryset(self):
        qs = LocationNode.objects.filter(is_active=True).select_related("location_type")

        parent_id = self.request.query_params.get("parent_id") or self.request.query_params.get("parent")
        if parent_id:
            qs = qs.filter(parent_id=parent_id)

        level = self.request.query_params.get("level") or self.request.query_params.get("location_type")
        if level:
            qs = qs.filter(location_type__code=level)

        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = LocationNode.objects.select_related("location_type")
            if is_active.lower() in ("true", "1"):
                qs = qs.filter(is_active=True)
            elif is_active.lower() in ("false", "0"):
                qs = qs.filter(is_active=False)

            if parent_id:
                qs = qs.filter(parent_id=parent_id)
            if level:
                qs = qs.filter(location_type__code=level)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search)

        return qs.order_by("depth", "name")


class LocationTreeView(APIView):
    """GET /api/locations/tree — full nested location tree."""

    permission_classes = [IsAuthenticated, permission_required("location.view")]

    def get(self, request):
        tree = build_location_tree()
        return Response(tree)


class LocationDetailView(RetrieveAPIView):
    """GET /api/locations/{id} — single location detail."""

    permission_classes = [IsAuthenticated, permission_required("location.view")]
    serializer_class = LocationNodeSerializer
    queryset = LocationNode.objects.filter(is_active=True).select_related("location_type")
    lookup_field = "pk"


class LocationHierarchyView(APIView):
    """GET /api/locations/hierarchy — compat alias for /tree."""

    permission_classes = [IsAuthenticated, permission_required("location.view")]

    def get(self, request):
        tree = build_location_tree()
        return Response(tree)


class LocationByLevelView(ListAPIView):
    """GET /api/locations/<level_code> — list nodes by location type code."""

    permission_classes = [IsAuthenticated, permission_required("location.view")]
    serializer_class = LocationNodeSerializer
    pagination_class = None

    def get_queryset(self):
        level = self.kwargs.get("level_code")
        qs = LocationNode.objects.filter(
            is_active=True, location_type__code=level
        ).select_related("location_type")

        parent_id = self.request.query_params.get("parent_id") or self.request.query_params.get("parent")
        if parent_id:
            qs = qs.filter(parent_id=parent_id)

        return qs.order_by("name")
