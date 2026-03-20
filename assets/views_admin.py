"""
Superadmin views for asset lookup table management.
"""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.permissions import IsSuperAdmin
from assets.models import AssetCategory, AssetSubType, BusinessEntity, CostCenter, Supplier
from assets.serializers_admin import (
    AdminCategorySerializer,
    AdminCostCenterSerializer,
    AdminBusinessEntitySerializer,
    AdminSubTypeSerializer,
    AdminSupplierSerializer,
)


def _apply_common_filters(qs, request, search_fields):
    search = request.query_params.get("search")
    if search:
        q = Q()
        for field in search_fields:
            q |= Q(**{f"{field}__icontains": search})
        qs = qs.filter(q)
    is_active = request.query_params.get("is_active")
    if is_active is not None:
        active_val = is_active.lower() in ("true", "1", "yes")
        qs = qs.filter(is_active=active_val)
    return qs


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class AdminCategoryListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = _apply_common_filters(AssetCategory.objects.all(), request, ["code", "name"])
        return Response(AdminCategorySerializer(qs, many=True).data)

    def post(self, request):
        code = request.data.get("code", "").strip()
        name = request.data.get("name", "").strip()
        errors = {}
        if not code:
            errors["code"] = ["This field is required."]
        elif AssetCategory.objects.filter(code=code).exists():
            errors["code"] = ["A category with this code already exists."]
        if not name:
            errors["name"] = ["This field is required."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        obj = AssetCategory.objects.create(
            code=code,
            name=name,
            is_active=request.data.get("is_active", True),
        )
        return Response(AdminCategorySerializer(obj).data, status=status.HTTP_201_CREATED)


class AdminCategoryDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        obj = get_object_or_404(AssetCategory, pk=pk)
        return Response(AdminCategorySerializer(obj).data)

    def patch(self, request, pk):
        obj = get_object_or_404(AssetCategory, pk=pk)
        for field in ("name", "is_active"):
            if field in request.data:
                setattr(obj, field, request.data[field])
        obj.save()
        return Response(AdminCategorySerializer(obj).data)


# ---------------------------------------------------------------------------
# SubType
# ---------------------------------------------------------------------------

class AdminSubTypeListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = AssetSubType.objects.select_related("category").all()
        qs = _apply_common_filters(qs, request, ["code", "name"])
        category_id = request.query_params.get("category_id")
        if category_id:
            qs = qs.filter(category_id=category_id)
        return Response(AdminSubTypeSerializer(qs, many=True).data)

    def post(self, request):
        code = request.data.get("code", "").strip()
        name = request.data.get("name", "").strip()
        category_id = request.data.get("category_id")
        errors = {}
        if not code:
            errors["code"] = ["This field is required."]
        if not name:
            errors["name"] = ["This field is required."]
        if not category_id:
            errors["category_id"] = ["This field is required."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        category = get_object_or_404(AssetCategory, pk=category_id)
        if AssetSubType.objects.filter(category=category, code=code).exists():
            return Response(
                {"code": ["A sub-type with this code already exists for this category."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        obj = AssetSubType.objects.create(
            category=category,
            code=code,
            name=name,
            is_active=request.data.get("is_active", True),
        )
        return Response(AdminSubTypeSerializer(obj).data, status=status.HTTP_201_CREATED)


class AdminSubTypeDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        obj = get_object_or_404(AssetSubType.objects.select_related("category"), pk=pk)
        return Response(AdminSubTypeSerializer(obj).data)

    def patch(self, request, pk):
        obj = get_object_or_404(AssetSubType.objects.select_related("category"), pk=pk)
        for field in ("name", "is_active"):
            if field in request.data:
                setattr(obj, field, request.data[field])
        obj.save()
        return Response(AdminSubTypeSerializer(obj).data)


# ---------------------------------------------------------------------------
# BusinessEntity
# ---------------------------------------------------------------------------

class AdminBusinessEntityListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = _apply_common_filters(BusinessEntity.objects.all(), request, ["code", "name"])
        return Response(AdminBusinessEntitySerializer(qs, many=True).data)

    def post(self, request):
        code = request.data.get("code", "").strip()
        name = request.data.get("name", "").strip()
        errors = {}
        if not code:
            errors["code"] = ["This field is required."]
        elif BusinessEntity.objects.filter(code=code).exists():
            errors["code"] = ["A business entity with this code already exists."]
        if not name:
            errors["name"] = ["This field is required."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        obj = BusinessEntity.objects.create(
            code=code,
            name=name,
            is_active=request.data.get("is_active", True),
        )
        return Response(AdminBusinessEntitySerializer(obj).data, status=status.HTTP_201_CREATED)


class AdminBusinessEntityDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        obj = get_object_or_404(BusinessEntity, pk=pk)
        return Response(AdminBusinessEntitySerializer(obj).data)

    def patch(self, request, pk):
        obj = get_object_or_404(BusinessEntity, pk=pk)
        for field in ("name", "is_active"):
            if field in request.data:
                setattr(obj, field, request.data[field])
        obj.save()
        return Response(AdminBusinessEntitySerializer(obj).data)


# ---------------------------------------------------------------------------
# CostCenter
# ---------------------------------------------------------------------------

class AdminCostCenterListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = _apply_common_filters(CostCenter.objects.all(), request, ["code", "name"])
        return Response(AdminCostCenterSerializer(qs, many=True).data)

    def post(self, request):
        code = request.data.get("code", "").strip()
        name = request.data.get("name", "").strip()
        errors = {}
        if not code:
            errors["code"] = ["This field is required."]
        elif CostCenter.objects.filter(code=code).exists():
            errors["code"] = ["A cost center with this code already exists."]
        if not name:
            errors["name"] = ["This field is required."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        obj = CostCenter.objects.create(
            code=code,
            name=name,
            is_active=request.data.get("is_active", True),
        )
        return Response(AdminCostCenterSerializer(obj).data, status=status.HTTP_201_CREATED)


class AdminCostCenterDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        obj = get_object_or_404(CostCenter, pk=pk)
        return Response(AdminCostCenterSerializer(obj).data)

    def patch(self, request, pk):
        obj = get_object_or_404(CostCenter, pk=pk)
        for field in ("name", "is_active"):
            if field in request.data:
                setattr(obj, field, request.data[field])
        obj.save()
        return Response(AdminCostCenterSerializer(obj).data)


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------

class AdminSupplierListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = _apply_common_filters(Supplier.objects.all(), request, ["code", "name"])
        return Response(AdminSupplierSerializer(qs, many=True).data)

    def post(self, request):
        code = request.data.get("code", "").strip() or None
        name = request.data.get("name", "").strip()
        errors = {}
        if not name:
            errors["name"] = ["This field is required."]
        if code and Supplier.objects.filter(code=code).exists():
            errors["code"] = ["A supplier with this code already exists."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        obj = Supplier.objects.create(
            code=code,
            name=name,
            email=request.data.get("email") or None,
            phone=request.data.get("phone") or None,
            is_active=request.data.get("is_active", True),
        )
        return Response(AdminSupplierSerializer(obj).data, status=status.HTTP_201_CREATED)


class AdminSupplierDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        obj = get_object_or_404(Supplier, pk=pk)
        return Response(AdminSupplierSerializer(obj).data)

    def patch(self, request, pk):
        obj = get_object_or_404(Supplier, pk=pk)
        for field in ("name", "email", "phone", "is_active"):
            if field in request.data:
                setattr(obj, field, request.data[field])
        obj.save()
        return Response(AdminSupplierSerializer(obj).data)
