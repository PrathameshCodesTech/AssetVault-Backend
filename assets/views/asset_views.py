import io
import json

import qrcode
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.helpers import (
    filter_by_location_scope,
    get_user_permission_codes,
    location_in_scope,
)
from access.permissions import permission_required
from assets.models import (
    Asset,
    AssetCategory,
    AssetEvent,
    AssetFinancialDetail,
    AssetImage,
    AssetSubType,
    AssetWFHDetail,
    BusinessEntity,
    CostCenter,
    Supplier,
)
from assets.serializers import (
    AssetAssignSerializer,
    AssetCategorySerializer,
    AssetCreateSerializer,
    AssetDetailSerializer,
    AssetEventSerializer,
    AssetListSerializer,
    AssetLookupsSerializer,
    AssetMoveSerializer,
    AssetSubTypeSerializer,
    AssetUpdateSerializer,
    BusinessEntitySerializer,
    CostCenterSerializer,
    SupplierSerializer,
    _FINANCIAL_FIELDS,
    _WFH_FIELDS,
)
from assets.services.asset_service import (
    assign_asset,
    build_asset_qr_payload,
    create_asset_event,
    move_asset,
    register_asset,
)
from locations.models import LocationNode

__all__ = [
    "AssetListCreateView",
    "AssetDetailView",
    "AssetHistoryView",
    "AssetAssignView",
    "AssetMoveView",
    "AssetScanView",
    "AssetQRView",
    "AssetLookupsView",
]


def _check_asset_in_scope(asset, user):
    """Return True if the asset's location is within the user's allowed scope."""
    from access.helpers import get_user_scope

    scope = get_user_scope(user)
    if scope["is_global"]:
        return True
    if not scope["location_ids"]:
        return False
    return asset.current_location_id in scope["location_ids"]


def _apply_financial(asset, data, update=False):
    """Create or update AssetFinancialDetail from validated serializer data."""
    fin_kwargs = {}
    for field in _FINANCIAL_FIELDS:
        if field in data:
            val = data[field]
            if field == "cost_center_id":
                if val:
                    try:
                        fin_kwargs["cost_center"] = CostCenter.objects.get(pk=val)
                    except CostCenter.DoesNotExist:
                        raise ValueError("Cost center not found.")
                else:
                    fin_kwargs["cost_center"] = None
            elif field == "supplier_id":
                if val:
                    try:
                        fin_kwargs["supplier"] = Supplier.objects.get(pk=val)
                    except Supplier.DoesNotExist:
                        raise ValueError("Supplier not found.")
                else:
                    fin_kwargs["supplier"] = None
            else:
                fin_kwargs[field] = val

    if not fin_kwargs:
        return

    if update:
        AssetFinancialDetail.objects.update_or_create(asset=asset, defaults=fin_kwargs)
    else:
        AssetFinancialDetail.objects.create(asset=asset, **fin_kwargs)


def _apply_wfh(asset, data, update=False):
    """Create or update AssetWFHDetail from validated serializer data."""
    wfh_kwargs = {f: data[f] for f in _WFH_FIELDS if f in data}
    if not wfh_kwargs:
        return
    if update:
        AssetWFHDetail.objects.update_or_create(asset=asset, defaults=wfh_kwargs)
    else:
        AssetWFHDetail.objects.create(asset=asset, **wfh_kwargs)


def _apply_image(asset, image_file):
    """Create a primary AssetImage for the given file."""
    if not image_file:
        return
    AssetImage.objects.create(asset=asset, image=image_file, is_primary=True)


def _annotate_employee_workflows(assets):
    """
    For each Asset in *assets* (already fetched), attach an ``_employee_workflow``
    attribute containing the active employee verification info, or None.

    Covers active request statuses only (not terminal approved/cancelled).
    Uses two extra queries total — not N+1.
    """
    if not assets:
        return
    from verification.models import (
        VerificationRequest,
        VerificationRequestAsset,
        AssetVerificationResponse,
    )

    _active = [
        VerificationRequest.Status.PENDING,
        VerificationRequest.Status.OPENED,
        VerificationRequest.Status.OTP_VERIFIED,
        VerificationRequest.Status.SUBMITTED,
        VerificationRequest.Status.CORRECTION_REQUESTED,
    ]
    asset_ids = [a.pk for a in assets]

    rows = list(
        VerificationRequestAsset.objects
        .filter(asset_id__in=asset_ids, verification_request__status__in=_active)
        .values(
            "asset_id", "id",
            "verification_request__id",
            "verification_request__reference_code",
            "verification_request__status",
            "verification_request__employee__first_name",
            "verification_request__employee__last_name",
        )
    )

    # One row per asset (cross-flow guards prevent duplicates)
    emp_map = {}  # asset_id -> row
    for row in rows:
        emp_map.setdefault(row["asset_id"], row)

    # Secondary: fill in approved terminal state for assets with no active request
    unmatched_ids = [pk for pk in asset_ids if pk not in emp_map]
    if unmatched_ids:
        approved_rows = list(
            VerificationRequestAsset.objects
            .filter(
                asset_id__in=unmatched_ids,
                verification_request__status=VerificationRequest.Status.APPROVED,
            )
            .order_by("-verification_request__updated_at")
            .values(
                "asset_id", "id",
                "verification_request__id",
                "verification_request__reference_code",
                "verification_request__status",
                "verification_request__employee__first_name",
                "verification_request__employee__last_name",
            )
        )
        # Keep only the most recent approved row per asset
        for row in approved_rows:
            emp_map.setdefault(row["asset_id"], row)

    # For SUBMITTED requests, get per-asset admin review status (one extra query)
    submitted_vra_ids = [
        row["id"] for row in emp_map.values()
        if row["verification_request__status"] == VerificationRequest.Status.SUBMITTED
    ]
    review_map = {}
    if submitted_vra_ids:
        for r in AssetVerificationResponse.objects.filter(
            request_asset_id__in=submitted_vra_ids
        ).values("request_asset_id", "admin_review_status"):
            review_map[r["request_asset_id"]] = r["admin_review_status"]

    def _derive(row):
        req_status = row["verification_request__status"]
        if req_status == VerificationRequest.Status.APPROVED:
            return "approved", "Approved"
        if req_status == VerificationRequest.Status.SUBMITTED:
            review = review_map.get(row["id"], AssetVerificationResponse.AdminReviewStatus.PENDING_REVIEW)
            if review == AssetVerificationResponse.AdminReviewStatus.APPROVED:
                return "approved", "Approved"
            if review == AssetVerificationResponse.AdminReviewStatus.CORRECTION_REQUIRED:
                return "correction_requested", "Correction Requested"
            return "under_review", "Under Review"
        if req_status == VerificationRequest.Status.PENDING:
            return "sent", "Sent"
        if req_status in (VerificationRequest.Status.OPENED, VerificationRequest.Status.OTP_VERIFIED):
            return "opened", "Opened"
        if req_status == VerificationRequest.Status.CORRECTION_REQUESTED:
            return "correction_requested", "Correction Requested"
        return "in_progress", "In Progress"

    for asset in assets:
        row = emp_map.get(asset.pk)
        if row:
            sk, sd = _derive(row)
            fn = row.get("verification_request__employee__first_name") or ""
            ln = row.get("verification_request__employee__last_name") or ""
            asset._employee_workflow = {
                "request_id": row["verification_request__id"],
                "reference_code": row["verification_request__reference_code"],
                "status_key": sk,
                "status_display": sd,
                "employee_name": f"{fn} {ln}".strip() or None,
            }
        else:
            asset._employee_workflow = None


_VENDOR_WORKFLOW_MAP = {
    "draft": ("draft", "Draft"),
    "sent": ("sent", "Sent"),
    "in_progress": ("in_progress", "In Progress"),
    "submitted": ("under_review", "Under Review"),
    "correction_requested": ("correction_requested", "Correction Requested"),
    "approved": ("approved", "Approved"),
}


def _annotate_workflow_status(assets):
    """
    Combine ``_employee_workflow`` and ``_vendor_reservation`` into a single
    ``_workflow`` dict on each asset.

    Priority: active employee request > active vendor request > None (available).
    Assumes both upstream annotations have already been called.
    """
    for asset in assets:
        emp = getattr(asset, "_employee_workflow", None)
        vendor = getattr(asset, "_vendor_reservation", None)
        if emp:
            asset._workflow = {
                "type": "employee",
                "status": emp["status_key"],
                "reference": emp["reference_code"],
                "display": f"Employee · {emp['status_display']}",
                "actor_name": emp.get("employee_name"),
            }
        elif vendor:
            v_status = vendor.get("status", "")
            sk, sd = _VENDOR_WORKFLOW_MAP.get(v_status, (v_status, v_status.replace("_", " ").title()))
            asset._workflow = {
                "type": "vendor",
                "status": sk,
                "reference": vendor.get("reference_code"),
                "display": f"Vendor · {sd}",
                "actor_name": vendor.get("vendor_name"),
            }
        else:
            asset._workflow = None


def _annotate_vendor_reservations(assets):
    """
    For each Asset in *assets* (already fetched), attach a ``_vendor_reservation``
    attribute containing the active vendor request info, or None if not reserved.

    Executes a single extra query rather than N+1.
    """
    if not assets:
        return
    from vendors.models import VendorVerificationRequest, VendorVerificationRequestAsset

    _vendor_active = [
        VendorVerificationRequest.Status.DRAFT,
        VendorVerificationRequest.Status.SENT,
        VendorVerificationRequest.Status.IN_PROGRESS,
        VendorVerificationRequest.Status.SUBMITTED,
        VendorVerificationRequest.Status.CORRECTION_REQUESTED,
    ]
    asset_ids = [a.pk for a in assets]
    rows = (
        VendorVerificationRequestAsset.objects
        .filter(asset_id__in=asset_ids, request__status__in=_vendor_active)
        .select_related("request", "request__vendor")
        .values("asset_id", "request_id", "request__reference_code", "request__status", "request__vendor__name")
    )
    mapping = {}
    for row in rows:
        mapping[row["asset_id"]] = {
            "request_id": row["request_id"],
            "reference_code": row["request__reference_code"],
            "status": row["request__status"],
            "vendor_name": row["request__vendor__name"],
        }

    # Secondary: fill in approved terminal state for assets with no active vendor request
    unmatched_vendor_ids = [pk for pk in asset_ids if pk not in mapping]
    if unmatched_vendor_ids:
        approved_vendor_rows = (
            VendorVerificationRequestAsset.objects
            .filter(
                asset_id__in=unmatched_vendor_ids,
                request__status=VendorVerificationRequest.Status.APPROVED,
            )
            .order_by("-request__updated_at")
            .values("asset_id", "request_id", "request__reference_code", "request__status", "request__vendor__name")
        )
        for row in approved_vendor_rows:
            mapping.setdefault(row["asset_id"], {
                "request_id": row["request_id"],
                "reference_code": row["request__reference_code"],
                "status": row["request__status"],
                "vendor_name": row["request__vendor__name"],
            })

    for asset in assets:
        asset._vendor_reservation = mapping.get(asset.pk)


class AssetListCreateView(APIView):
    """
    GET  /api/assets/ — list assets (requires asset.view)
    POST /api/assets/ — create a new asset (requires asset.create)
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        perms = super().get_permissions()
        if self.request.method == "POST":
            perms.append(permission_required("asset.create")())
        else:
            perms.append(permission_required("asset.view")())
        return perms

    def get(self, request):
        qs = Asset.objects.select_related(
            "category",
            "sub_type",
            "business_entity",
            "current_location",
            "current_location__location_type",
            "assigned_to",
        ).order_by("-created_at")

        qs = filter_by_location_scope(qs, request.user)

        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category__code=category)

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        reconciliation_status = request.query_params.get("reconciliation_status")
        if reconciliation_status:
            qs = qs.filter(reconciliation_status=reconciliation_status)

        location_id = request.query_params.get("location_id")
        if location_id:
            qs = qs.filter(current_location_id=location_id)

        assigned_to = request.query_params.get("assigned_to")
        if assigned_to:
            qs = qs.filter(assigned_to_id=assigned_to)

        is_mapped = request.query_params.get("is_mapped")
        if is_mapped is not None:
            if is_mapped.lower() == "false":
                qs = qs.filter(assigned_to__isnull=True)
            elif is_mapped.lower() == "true":
                qs = qs.filter(assigned_to__isnull=False)

        entity = request.query_params.get("entity")
        if entity:
            qs = qs.filter(business_entity__code=entity)

        search = request.query_params.get("search")
        if search:
            from django.db.models import Q

            qs = qs.filter(
                Q(asset_id__icontains=search)
                | Q(name__icontains=search)
                | Q(serial_number__icontains=search)
                | Q(tag_number__icontains=search)
            )

        vendor_id = request.query_params.get("vendor_id")
        if vendor_id:
            from vendors.models import VendorVerificationRequest, VendorVerificationRequestAsset
            _vendor_active = [
                VendorVerificationRequest.Status.DRAFT,
                VendorVerificationRequest.Status.SENT,
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.SUBMITTED,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
            ]
            vendor_reserved_ids = VendorVerificationRequestAsset.objects.filter(
                request__vendor_id=vendor_id,
                request__status__in=_vendor_active,
            ).values_list("asset_id", flat=True)
            qs = qs.filter(pk__in=vendor_reserved_ids)

        vendor_linked = request.query_params.get("vendor_linked")
        if vendor_linked is not None:
            from vendors.models import VendorVerificationRequest, VendorVerificationRequestAsset
            _vendor_active = [
                VendorVerificationRequest.Status.DRAFT,
                VendorVerificationRequest.Status.SENT,
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.SUBMITTED,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
            ]
            vendor_reserved_ids = VendorVerificationRequestAsset.objects.filter(
                request__status__in=_vendor_active,
            ).values_list("asset_id", flat=True)
            if vendor_linked.lower() in ("true", "1"):
                qs = qs.filter(pk__in=vendor_reserved_ids)
            else:
                qs = qs.exclude(pk__in=vendor_reserved_ids)

        ordering = request.query_params.get("ordering", "-created_at")
        allowed_orderings = {
            "created_at", "-created_at", "name", "-name",
            "asset_id", "-asset_id", "status", "-status",
        }
        if ordering in allowed_orderings:
            qs = qs.order_by(ordering)

        from rest_framework.pagination import PageNumberPagination

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 25))
        page = paginator.paginate_queryset(qs, request)

        # Annotate each asset with workflow state (vendor + employee → unified)
        _annotate_vendor_reservations(page)
        _annotate_employee_workflows(page)
        _annotate_workflow_status(page)

        serializer = AssetListSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = AssetCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            category = AssetCategory.objects.get(pk=data["category_id"])
        except AssetCategory.DoesNotExist:
            return Response(
                {"detail": "Category not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            location = LocationNode.objects.get(pk=data["current_location_id"])
        except LocationNode.DoesNotExist:
            return Response(
                {"detail": "Location not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not location_in_scope(location.pk, request.user):
            return Response(
                {"detail": "Target location is outside your allowed scope."},
                status=status.HTTP_403_FORBIDDEN,
            )

        kwargs = {}
        for field in [
            "serial_number", "tag_number", "description", "sub_location_text",
            "status", "currency_code", "purchase_value", "capitalized_on",
            "asset_class", "is_wfh_asset",
        ]:
            if field in data and data[field] is not None:
                kwargs[field] = data[field]

        if "sub_type_id" in data and data["sub_type_id"]:
            try:
                kwargs["sub_type"] = AssetSubType.objects.get(pk=data["sub_type_id"])
            except AssetSubType.DoesNotExist:
                return Response({"detail": "Sub type not found."}, status=status.HTTP_400_BAD_REQUEST)

        if "business_entity_id" in data and data["business_entity_id"]:
            try:
                kwargs["business_entity"] = BusinessEntity.objects.get(pk=data["business_entity_id"])
            except BusinessEntity.DoesNotExist:
                return Response({"detail": "Business entity not found."}, status=status.HTTP_400_BAD_REQUEST)

        if "assigned_to_id" in data and data["assigned_to_id"]:
            from accounts.models import User

            try:
                kwargs["assigned_to"] = User.objects.get(pk=data["assigned_to_id"])
            except User.DoesNotExist:
                return Response({"detail": "User not found."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                asset = register_asset(
                    asset_id=data["asset_id"],
                    name=data["name"],
                    category=category,
                    current_location=location,
                    created_by=request.user,
                    **kwargs,
                )
                _apply_financial(asset, data, update=False)
                _apply_wfh(asset, data, update=False)
                _apply_image(asset, request.FILES.get("image"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        asset = Asset.objects.select_related(
            "category", "sub_type", "business_entity",
            "current_location", "current_location__location_type", "assigned_to",
        ).get(pk=asset.pk)
        result = AssetDetailSerializer(asset, context={"request": request}).data
        return Response(result, status=status.HTTP_201_CREATED)


class AssetDetailView(APIView):
    """
    GET   /api/assets/{id}/ — full detail (requires asset.view)
    PATCH /api/assets/{id}/ — partial update (requires asset.update)
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        perms = super().get_permissions()
        if self.request.method == "PATCH":
            perms.append(permission_required("asset.update")())
        else:
            perms.append(permission_required("asset.view")())
        return perms

    def _get_scoped_asset(self, pk, user):
        asset = Asset.objects.select_related(
            "category", "sub_type", "business_entity",
            "current_location", "current_location__location_type", "assigned_to",
        ).get(pk=pk)
        if not _check_asset_in_scope(asset, user):
            return None
        return asset

    def get(self, request, pk):
        try:
            asset = self._get_scoped_asset(pk, request.user)
        except Asset.DoesNotExist:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)
        if asset is None:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = AssetDetailSerializer(asset, context={"request": request})
        return Response(serializer.data)

    def patch(self, request, pk):
        try:
            asset = self._get_scoped_asset(pk, request.user)
        except Asset.DoesNotExist:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)
        if asset is None:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AssetUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_fields = []
        for field in [
            "name", "serial_number", "tag_number", "description",
            "sub_location_text", "status", "currency_code",
            "purchase_value", "capitalized_on", "asset_class",
        ]:
            if field in data:
                setattr(asset, field, data[field])
                update_fields.append(field)

        if "category_id" in data:
            try:
                asset.category = AssetCategory.objects.get(pk=data["category_id"])
                update_fields.append("category")
            except AssetCategory.DoesNotExist:
                return Response({"detail": "Category not found."}, status=status.HTTP_400_BAD_REQUEST)

        if "sub_type_id" in data:
            if data["sub_type_id"]:
                try:
                    asset.sub_type = AssetSubType.objects.get(pk=data["sub_type_id"])
                except AssetSubType.DoesNotExist:
                    return Response({"detail": "Sub type not found."}, status=status.HTTP_400_BAD_REQUEST)
            else:
                asset.sub_type = None
            update_fields.append("sub_type")

        if "business_entity_id" in data:
            if data["business_entity_id"]:
                try:
                    asset.business_entity = BusinessEntity.objects.get(pk=data["business_entity_id"])
                except BusinessEntity.DoesNotExist:
                    return Response({"detail": "Business entity not found."}, status=status.HTTP_400_BAD_REQUEST)
            else:
                asset.business_entity = None
            update_fields.append("business_entity")

        if "current_location_id" in data:
            try:
                new_location = LocationNode.objects.get(pk=data["current_location_id"])
            except LocationNode.DoesNotExist:
                return Response({"detail": "Location not found."}, status=status.HTTP_400_BAD_REQUEST)
            if not location_in_scope(new_location.pk, request.user):
                return Response(
                    {"detail": "Target location is outside your allowed scope."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            asset.current_location = new_location
            update_fields.append("current_location")

        if "assigned_to_id" in data:
            if data["assigned_to_id"]:
                from accounts.models import User
                try:
                    asset.assigned_to = User.objects.get(pk=data["assigned_to_id"])
                except User.DoesNotExist:
                    return Response({"detail": "User not found."}, status=status.HTTP_400_BAD_REQUEST)
            else:
                asset.assigned_to = None
            update_fields.append("assigned_to")

        try:
            with transaction.atomic():
                if update_fields:
                    asset.updated_by = request.user
                    update_fields.append("updated_by")
                    update_fields.append("updated_at")
                    asset.save(update_fields=update_fields)
                    create_asset_event(
                        asset, AssetEvent.EventType.UPDATED,
                        actor=request.user, description="Asset updated.",
                    )
                _apply_financial(asset, data, update=True)
                _apply_wfh(asset, data, update=True)
                if request.FILES.get("image"):
                    _apply_image(asset, request.FILES.get("image"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        asset = Asset.objects.select_related(
            "category", "sub_type", "business_entity",
            "current_location", "current_location__location_type", "assigned_to",
        ).get(pk=asset.pk)
        result = AssetDetailSerializer(asset, context={"request": request}).data
        return Response(result)


class AssetHistoryView(APIView):
    """GET /api/assets/{id}/history — asset event timeline (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("asset.view")]

    def get(self, request, pk):
        try:
            asset = Asset.objects.get(pk=pk)
        except Asset.DoesNotExist:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _check_asset_in_scope(asset, request.user):
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        events = (
            AssetEvent.objects.filter(asset_id=pk)
            .select_related("actor", "from_location", "to_location")
            .order_by("-created_at")
        )
        serializer = AssetEventSerializer(events, many=True)
        return Response(serializer.data)


class AssetAssignView(APIView):
    """POST /api/assets/{id}/assign — assign asset to user (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("asset.assign")]

    def post(self, request, pk):
        try:
            asset = Asset.objects.get(pk=pk)
        except Asset.DoesNotExist:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _check_asset_in_scope(asset, request.user):
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AssetAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from accounts.models import User

        try:
            user = User.objects.get(pk=data["user_id"])
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        start_at = data.get("start_at", timezone.now())
        note = data.get("note", "")
        force_reassign = str(request.data.get("force_reassign", "false")).lower() in ("true", "1")

        # ── Cross-flow guards ─────────────────────────────────────────────
        # Block if the asset is in an active vendor verification request.
        try:
            from vendors.models import VendorVerificationRequest, VendorVerificationRequestAsset
            _ACTIVE_VENDOR_STATUSES = [
                VendorVerificationRequest.Status.SENT,
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.SUBMITTED,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
            ]
            active_vendor_ra = (
                VendorVerificationRequestAsset.objects
                .filter(asset=asset, request__status__in=_ACTIVE_VENDOR_STATUSES)
                .select_related("request")
                .first()
            )
            if active_vendor_ra:
                return Response(
                    {
                        "detail": (
                            f"Asset '{asset.asset_id}' is part of active vendor request "
                            f"{active_vendor_ra.request.reference_code}. "
                            f"Complete or cancel the vendor request before reassigning."
                        ),
                        "conflict_type": "active_vendor_request",
                        "request_reference": active_vendor_ra.request.reference_code,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
        except ImportError:
            pass  # vendors app not installed

        # Block (or warn-override) if the asset is in an active employee verification request.
        from verification.models import VerificationRequest, VerificationRequestAsset as VRA
        active_vra = (
            VRA.objects
            .filter(asset=asset, verification_request__status__in=list(VerificationRequest.ACTIVE_STATUSES))
            .select_related("verification_request", "verification_request__employee")
            .first()
        )
        if active_vra and not force_reassign:
            emp = active_vra.verification_request.employee
            return Response(
                {
                    "detail": (
                        f"Asset '{asset.asset_id}' is in active verification request "
                        f"{active_vra.verification_request.reference_code} for employee "
                        f"'{emp.get_full_name() or emp.email}'. "
                        f"Cancel that request first, or pass force_reassign=true to override."
                    ),
                    "conflict_type": "active_employee_request",
                    "request_reference": active_vra.verification_request.reference_code,
                    "employee_name": emp.get_full_name() or emp.email,
                    "employee_email": emp.email,
                },
                status=status.HTTP_409_CONFLICT,
            )
        # ─────────────────────────────────────────────────────────────────
        # Eviction + assignment in one atomic unit.
        # If force_reassign is set and the asset is in an active employee
        # verification request, remove it from that request before reassigning.
        # If that request becomes empty, cancel it.
        try:
            from django.db import transaction as _tx

            with _tx.atomic():
                if force_reassign and active_vra is not None:
                    from verification.models import VerificationRequest
                    from verification.services.request_service import cancel_verification_request

                    old_request = active_vra.verification_request
                    active_vra.delete()
                    if old_request.request_assets.count() == 0:
                        try:
                            cancel_verification_request(
                                old_request,
                                cancelled_by=request.user,
                            )
                        except Exception:
                            pass  # already in a terminal state — safe to skip

                assignment = assign_asset(asset, user, start_at, assigned_by=request.user, note=note)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"detail": "Asset assigned.", "assignment_id": str(assignment.pk)},
            status=status.HTTP_200_OK,
        )


class AssetMoveView(APIView):
    """POST /api/assets/{id}/move — move asset to new location (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("asset.update")]

    def post(self, request, pk):
        try:
            asset = Asset.objects.get(pk=pk)
        except Asset.DoesNotExist:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _check_asset_in_scope(asset, request.user):
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AssetMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            to_location = LocationNode.objects.get(pk=data["to_location_id"])
        except LocationNode.DoesNotExist:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)

        if not location_in_scope(to_location.pk, request.user):
            return Response(
                {"detail": "Target location is outside your allowed scope."},
                status=status.HTTP_403_FORBIDDEN,
            )

        note = data.get("note", "")

        try:
            event = move_asset(asset, to_location, actor=request.user, note=note)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"detail": "Asset moved.", "event_id": str(event.pk)},
            status=status.HTTP_200_OK,
        )


class AssetScanView(APIView):
    """GET /api/assets/scan/{qr_uid}/ — lookup asset by QR UID (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("asset.view")]

    def get(self, request, qr_uid):
        try:
            asset = Asset.objects.select_related(
                "category", "sub_type", "business_entity",
                "current_location", "current_location__location_type", "assigned_to",
            ).get(qr_uid=qr_uid)
        except Asset.DoesNotExist:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _check_asset_in_scope(asset, request.user):
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AssetDetailSerializer(asset, context={"request": request})
        return Response(serializer.data)


class AssetQRView(APIView):
    """GET /api/assets/{id}/qr/ — generate QR code image (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("asset.view")]

    def get(self, request, pk):
        try:
            asset = Asset.objects.select_related("category", "current_location").get(pk=pk)
        except Asset.DoesNotExist:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _check_asset_in_scope(asset, request.user):
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = build_asset_qr_payload(asset)
        fmt = request.query_params.get("format", "png")

        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(json.dumps(payload))
        qr.make(fit=True)

        if fmt == "svg":
            import qrcode.image.svg

            factory = qrcode.image.svg.SvgImage
            img = qr.make_image(image_factory=factory)
            buf = io.BytesIO()
            img.save(buf)
            return HttpResponse(buf.getvalue(), content_type="image/svg+xml")
        else:
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return HttpResponse(buf.getvalue(), content_type="image/png")


class AssetLookupsView(APIView):
    """GET /api/assets/lookups/ — all lookup data for asset forms."""

    permission_classes = [IsAuthenticated, permission_required("asset.view")]

    def get(self, request):
        categories_qs = AssetCategory.objects.filter(is_active=True)
        sub_types_qs = AssetSubType.objects.filter(is_active=True).select_related("category")
        entities_qs = BusinessEntity.objects.filter(is_active=True)
        cost_centers_qs = CostCenter.objects.filter(is_active=True)
        suppliers_qs = Supplier.objects.filter(is_active=True)

        categories_data = AssetCategorySerializer(categories_qs, many=True).data
        sub_types_data = AssetSubTypeSerializer(sub_types_qs, many=True).data
        entities_data = BusinessEntitySerializer(entities_qs, many=True).data
        cost_centers_data = CostCenterSerializer(cost_centers_qs, many=True).data
        suppliers_data = SupplierSerializer(suppliers_qs, many=True).data

        data = {
            "categories": categories_data,
            "subTypes": sub_types_data,
            "entities": entities_data,
            "costCenters": cost_centers_data,
            "suppliers": suppliers_data,
            # Compatibility aliases
            "sub_types": sub_types_data,
            "business_entities": entities_data,
            "cost_centers": cost_centers_data,
            # Enum lookups
            "assetStatuses": [
                {"value": c[0], "label": c[1]} for c in Asset.Status.choices
            ],
            "reconciliationStatuses": [
                {"value": c[0], "label": c[1]} for c in Asset.ReconciliationStatus.choices
            ],
        }
        return Response(data)
