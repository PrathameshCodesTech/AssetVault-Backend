"""
Admin and superadmin views for vendor management and vendor verification requests.

Superadmin-only: vendor org CRUD, user assignments.
Admin (location_admin + super_admin): create/manage/review vendor verification requests.
"""
import datetime

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.helpers import get_user_scope, location_in_scope
from access.permissions import IsSuperAdmin, permission_required
from assets.models import Asset
from vendors.models import (
    VendorOrganization,
    VendorUserAssignment,
    VendorVerificationRequest,
    VendorVerificationRequestAsset,
)
from vendors.serializers import (
    VendorOrganizationSerializer,
    VendorUserAssignmentSerializer,
    VendorVerificationRequestDetailSerializer,
    VendorVerificationRequestSerializer,
)


# ---------------------------------------------------------------------------
# Superadmin: Vendor Organization CRUD
# ---------------------------------------------------------------------------

class AdminVendorListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = VendorOrganization.objects.prefetch_related("user_assignments").all()
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ("true", "1"))
        return Response(VendorOrganizationSerializer(qs, many=True).data)

    def post(self, request):
        code = request.data.get("code", "").strip()
        name = request.data.get("name", "").strip()

        errors = {}
        if not code:
            errors["code"] = ["This field is required."]
        elif VendorOrganization.objects.filter(code=code).exists():
            errors["code"] = ["A vendor with this code already exists."]
        if not name:
            errors["name"] = ["This field is required."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        vendor = VendorOrganization.objects.create(
            code=code,
            name=name,
            contact_email=request.data.get("contact_email") or None,
            contact_phone=request.data.get("contact_phone") or None,
            notes=request.data.get("notes") or None,
        )
        return Response(VendorOrganizationSerializer(vendor).data, status=status.HTTP_201_CREATED)


class AdminVendorDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        vendor = get_object_or_404(VendorOrganization, pk=pk)
        return Response(VendorOrganizationSerializer(vendor).data)

    def patch(self, request, pk):
        vendor = get_object_or_404(VendorOrganization, pk=pk)
        for field in ("name", "contact_email", "contact_phone", "notes", "is_active"):
            if field in request.data:
                setattr(vendor, field, request.data[field] or None if field != "is_active" else request.data[field])
        vendor.save()
        return Response(VendorOrganizationSerializer(vendor).data)


# ---------------------------------------------------------------------------
# Superadmin: Vendor User Assignments
# ---------------------------------------------------------------------------

class AdminVendorUserListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, pk):
        vendor = get_object_or_404(VendorOrganization, pk=pk)
        qs = VendorUserAssignment.objects.select_related("user").filter(vendor=vendor)
        return Response(VendorUserAssignmentSerializer(qs, many=True).data)

    def post(self, request, pk):
        from accounts.models import User

        vendor = get_object_or_404(VendorOrganization, pk=pk)
        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"user_id": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

        user = get_object_or_404(User, pk=user_id)

        # Check if user already has an active assignment to any vendor
        existing = VendorUserAssignment.objects.filter(user=user, is_active=True).first()
        if existing:
            return Response(
                {"detail": f"User is already assigned to vendor '{existing.vendor.name}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignment, created = VendorUserAssignment.objects.get_or_create(
            vendor=vendor, user=user, defaults={"is_active": True}
        )
        if not created:
            if not assignment.is_active:
                assignment.is_active = True
                assignment.save()
            else:
                return Response(
                    {"detail": "User is already assigned to this vendor."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(VendorUserAssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)


class AdminVendorUserRemoveView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def delete(self, request, pk, assignment_id):
        vendor = get_object_or_404(VendorOrganization, pk=pk)
        assignment = get_object_or_404(VendorUserAssignment, pk=assignment_id, vendor=vendor)
        assignment.is_active = False
        assignment.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin: Vendor Verification Request — create and list
# ---------------------------------------------------------------------------

def _scope_vendor_requests(qs, user):
    """
    Filter a VendorVerificationRequest queryset to the requesting admin's
    location scope.  Super-admins (global scope) see everything; location-admins
    see only requests where ALL assets are within their allowed locations.

    Assets with a null current_location_id are treated as always in-scope
    (mirrors location_in_scope() helper behaviour).
    """
    scope = get_user_scope(user)
    if scope["is_global"]:
        return qs
    if not scope["location_ids"]:
        return qs.none()
    # Exclude any request that has at least one asset with a non-null location
    # that is NOT in the admin's allowed set.
    out_of_scope_request_ids = (
        VendorVerificationRequestAsset.objects
        .filter(request__in=qs, asset__current_location_id__isnull=False)
        .exclude(asset__current_location_id__in=scope["location_ids"])
        .values_list("request_id", flat=True)
        .distinct()
    )
    return qs.exclude(pk__in=out_of_scope_request_ids)


def _vendor_request_in_scope(pk, user):
    """
    Fetch a VendorVerificationRequest by pk and verify the requesting admin
    has location-scope access to it.  Returns (vr, error_response).

    Access requires ALL assets in the request to be within the admin's scope
    (assets with a null current_location_id are treated as in-scope).
    """
    from django.shortcuts import get_object_or_404
    vr = get_object_or_404(VendorVerificationRequest, pk=pk)
    scope = get_user_scope(user)
    if scope["is_global"]:
        return vr, None
    if not scope["location_ids"]:
        return None, Response({"detail": "You have no location scope assigned."}, status=status.HTTP_403_FORBIDDEN)
    has_out_of_scope = (
        vr.request_assets
        .filter(asset__current_location_id__isnull=False)
        .exclude(asset__current_location_id__in=scope["location_ids"])
        .exists()
    )
    if has_out_of_scope:
        return None, Response({"detail": "You do not have access to this vendor request."}, status=status.HTTP_403_FORBIDDEN)
    return vr, None


class AdminVendorRequestListCreateView(APIView):
    permission_classes = [IsAuthenticated, permission_required("vendor.request")]

    def get(self, request):
        qs = VendorVerificationRequest.objects.select_related("vendor", "requested_by").all()
        qs = _scope_vendor_requests(qs, request.user)
        vendor_id = request.query_params.get("vendor_id")
        req_status = request.query_params.get("status")
        if vendor_id:
            qs = qs.filter(vendor_id=vendor_id)
        if req_status:
            qs = qs.filter(status=req_status)
        return Response(VendorVerificationRequestSerializer(qs, many=True).data)

    def post(self, request):
        vendor_id = request.data.get("vendor_id")
        asset_ids = request.data.get("asset_ids", [])
        location_scope_id = request.data.get("location_scope_id")

        errors = {}
        if not vendor_id:
            errors["vendor_id"] = ["This field is required."]
        if not asset_ids:
            errors["asset_ids"] = ["At least one asset must be selected."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        vendor = get_object_or_404(VendorOrganization, pk=vendor_id, is_active=True)

        # Validate assets: must be unmapped (assigned_to IS NULL) and not in an active vendor request
        assets = Asset.objects.filter(pk__in=asset_ids)
        found_ids = {str(a.pk) for a in assets}
        missing = [aid for aid in asset_ids if aid not in found_ids]
        if missing:
            return Response(
                {"asset_ids": [f"Assets not found: {missing}"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Block employee-assigned assets
        mapped = [a for a in assets if a.assigned_to_id]
        if mapped:
            return Response(
                {"asset_ids": [f"Asset(s) {[a.asset_id for a in mapped]} are assigned to employees. Only unmapped assets can go to vendor requests."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Block assets that are in an active employee verification request
        # (belt-and-suspenders: unmapped assets shouldn't have one, but guard anyway)
        from verification.models import VerificationRequest, VerificationRequestAsset as VRA
        in_employee_request = (
            VRA.objects
            .filter(
                asset_id__in=asset_ids,
                verification_request__status__in=list(VerificationRequest.ACTIVE_STATUSES),
            )
            .select_related("asset", "verification_request")
        )
        if in_employee_request.exists():
            conflicts = [
                f"{vra.asset.asset_id} (in {vra.verification_request.reference_code})"
                for vra in in_employee_request
            ]
            return Response(
                {"asset_ids": [f"Asset(s) are in active employee verification requests: {conflicts}"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Block assets already in an active vendor request (including DRAFT)
        active_statuses = [
            VendorVerificationRequest.Status.DRAFT,
            VendorVerificationRequest.Status.SENT,
            VendorVerificationRequest.Status.IN_PROGRESS,
            VendorVerificationRequest.Status.SUBMITTED,
            VendorVerificationRequest.Status.CORRECTION_REQUESTED,
        ]
        already_active = VendorVerificationRequestAsset.objects.filter(
            asset_id__in=asset_ids,
            request__status__in=active_statuses,
        ).select_related("asset", "request")
        if already_active.exists():
            conflicts = [
                f"{ra.asset.asset_id} (in {ra.request.reference_code})"
                for ra in already_active
            ]
            return Response(
                {"asset_ids": [f"Asset(s) already in an active vendor request: {conflicts}"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Enforce location scope for non-global admins
        out_of_scope = [a for a in assets if not location_in_scope(a.current_location_id, request.user)]
        if out_of_scope:
            return Response(
                {"asset_ids": [f"Asset(s) {[a.asset_id for a in out_of_scope]} are outside your location scope."]},
                status=status.HTTP_403_FORBIDDEN,
            )

        location_scope = None
        if location_scope_id:
            from locations.models import LocationNode
            location_scope = get_object_or_404(LocationNode, pk=location_scope_id)

        vr = VendorVerificationRequest.objects.create(
            reference_code=VendorVerificationRequest.generate_reference_code(),
            vendor=vendor,
            requested_by=request.user,
            location_scope=location_scope,
            notes=request.data.get("notes") or None,
        )

        for asset in assets:
            VendorVerificationRequestAsset.objects.create(
                request=vr,
                asset=asset,
                asset_id_snapshot=asset.asset_id,
                asset_name_snapshot=asset.name,
                asset_location_snapshot=asset.current_location.name if asset.current_location_id else "",
            )

        return Response(
            VendorVerificationRequestDetailSerializer(vr).data,
            status=status.HTTP_201_CREATED,
        )


class AdminVendorRequestDetailView(APIView):
    permission_classes = [IsAuthenticated, permission_required("vendor.request")]

    def get(self, request, pk):
        vr, err = _vendor_request_in_scope(pk, request.user)
        if err:
            return err
        vr = VendorVerificationRequest.objects.select_related("vendor", "requested_by").get(pk=vr.pk)
        return Response(VendorVerificationRequestDetailSerializer(vr, context={"request": request}).data)

    def patch(self, request, pk):
        vr, err = _vendor_request_in_scope(pk, request.user)
        if err:
            return err
        if vr.status not in (VendorVerificationRequest.Status.DRAFT,):
            return Response(
                {"detail": "Only DRAFT requests can be edited."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "notes" in request.data:
            vr.notes = request.data["notes"] or None
        vr.save()
        return Response(VendorVerificationRequestDetailSerializer(vr, context={"request": request}).data)


class AdminVendorRequestSendView(APIView):
    """Transition a DRAFT request to SENT — vendor can now see it."""

    permission_classes = [IsAuthenticated, permission_required("vendor.request")]

    def post(self, request, pk):
        vr, err = _vendor_request_in_scope(pk, request.user)
        if err:
            return err
        if vr.status != VendorVerificationRequest.Status.DRAFT:
            return Response(
                {"detail": "Only DRAFT requests can be sent."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not vr.request_assets.exists():
            return Response(
                {"detail": "Cannot send an empty request."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        vr.status = VendorVerificationRequest.Status.SENT
        vr.sent_at = timezone.now()
        vr.save()

        # Notify all active vendor users — fire only after the DB write commits.
        _sent_by = request.user
        _vr_pk = vr.pk

        def _notify_new():
            from vendors.models import VendorVerificationRequest as _VVR
            from vendors.services.notification_service import send_vendor_request_notification
            try:
                _vr = _VVR.objects.select_related("vendor", "location_scope").get(pk=_vr_pk)
                send_vendor_request_notification(_vr, sent_by=_sent_by)
            except Exception:
                pass  # non-fatal; email failure must not affect the API response

        transaction.on_commit(_notify_new)

        return Response(VendorVerificationRequestSerializer(vr).data)


class AdminVendorRequestApproveView(APIView):
    permission_classes = [IsAuthenticated, permission_required("vendor.request")]

    def post(self, request, pk):
        vr, err = _vendor_request_in_scope(pk, request.user)
        if err:
            return err
        if vr.status != VendorVerificationRequest.Status.SUBMITTED:
            return Response(
                {"detail": "Only SUBMITTED requests can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Guard: cannot approve while any asset is marked correction_required
        if vr.request_assets.filter(
            admin_decision=VendorVerificationRequestAsset.AdminDecision.CORRECTION_REQUIRED
        ).exists():
            return Response(
                {"detail": "Cannot approve: some assets are marked Correction Required. Use 'Request Correction' instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        vr.status = VendorVerificationRequest.Status.APPROVED
        vr.reviewed_at = timezone.now()
        vr.reviewed_by = request.user
        vr.review_notes = request.data.get("review_notes") or None
        vr.save()
        # Mark all assets that are still pending_review as approved
        vr.request_assets.filter(
            admin_decision=VendorVerificationRequestAsset.AdminDecision.PENDING_REVIEW
        ).update(admin_decision=VendorVerificationRequestAsset.AdminDecision.APPROVED)
        return Response(VendorVerificationRequestDetailSerializer(vr, context={"request": request}).data)


class AdminVendorRequestCorrectionView(APIView):
    permission_classes = [IsAuthenticated, permission_required("vendor.request")]

    def post(self, request, pk):
        vr, err = _vendor_request_in_scope(pk, request.user)
        if err:
            return err
        if vr.status != VendorVerificationRequest.Status.SUBMITTED:
            return Response(
                {"detail": "Only SUBMITTED requests can be sent for correction."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        asset_decisions = request.data.get("asset_decisions", [])
        # asset_decisions: list of {request_asset_id, decision, notes}
        for d in asset_decisions:
            ra = vr.request_assets.filter(pk=d.get("request_asset_id")).first()
            if ra:
                ra.admin_decision = d.get("decision", ra.admin_decision)
                if "notes" in d:
                    ra.response_notes = d["notes"]
                ra.save()

        # Guard: at least one asset must be marked correction_required
        if not vr.request_assets.filter(
            admin_decision=VendorVerificationRequestAsset.AdminDecision.CORRECTION_REQUIRED
        ).exists():
            return Response(
                {"detail": "Cannot request correction: no assets are marked Correction Required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vr.status = VendorVerificationRequest.Status.CORRECTION_REQUESTED
        vr.reviewed_at = timezone.now()
        vr.reviewed_by = request.user
        vr.review_notes = request.data.get("review_notes") or None
        vr.save()

        # Count per-asset decisions for the notification (read after saves above).
        _approved_count = vr.request_assets.filter(
            admin_decision=VendorVerificationRequestAsset.AdminDecision.APPROVED
        ).count()
        _correction_count = vr.request_assets.filter(
            admin_decision=VendorVerificationRequestAsset.AdminDecision.CORRECTION_REQUIRED
        ).count()
        _reviewed_by = request.user
        _review_notes = vr.review_notes
        _vr_pk = vr.pk

        def _notify_correction():
            from vendors.models import VendorVerificationRequest as _VVR
            from vendors.services.notification_service import send_vendor_correction_notification
            try:
                _vr = _VVR.objects.select_related("vendor", "location_scope").get(pk=_vr_pk)
                send_vendor_correction_notification(
                    _vr,
                    reviewed_by=_reviewed_by,
                    approved_count=_approved_count,
                    correction_count=_correction_count,
                    note=_review_notes,
                )
            except Exception:
                pass  # non-fatal

        transaction.on_commit(_notify_correction)

        return Response(VendorVerificationRequestDetailSerializer(vr, context={"request": request}).data)


class AdminVendorRequestAssetDecisionView(APIView):
    """Set admin decision on a single asset within a submitted request."""

    permission_classes = [IsAuthenticated, permission_required("vendor.request")]

    def patch(self, request, pk, asset_pk):
        vr, err = _vendor_request_in_scope(pk, request.user)
        if err:
            return err
        ra = get_object_or_404(VendorVerificationRequestAsset, pk=asset_pk, request=vr)
        decision = request.data.get("admin_decision")
        if decision not in VendorVerificationRequestAsset.AdminDecision.values:
            return Response(
                {"admin_decision": [f"Must be one of: {VendorVerificationRequestAsset.AdminDecision.values}"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ra.admin_decision = decision
        if "response_notes" in request.data:
            ra.response_notes = request.data["response_notes"]
        ra.save()
        from vendors.serializers import VendorVerificationRequestAssetSerializer
        return Response(VendorVerificationRequestAssetSerializer(ra, context={"request": request}).data)


class AdminVendorRequestAssetRemoveView(APIView):
    """
    DELETE /api/admin/vendor-requests/{pk}/assets/{asset_pk}/

    Remove an asset from a DRAFT vendor request.
    If the request becomes empty it is automatically cancelled.
    """

    permission_classes = [IsAuthenticated, permission_required("vendor.request")]

    def delete(self, request, pk, asset_pk):
        vr, err = _vendor_request_in_scope(pk, request.user)
        if err:
            return err
        if vr.status != VendorVerificationRequest.Status.DRAFT:
            return Response(
                {"detail": "Assets can only be removed from DRAFT requests."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ra = get_object_or_404(VendorVerificationRequestAsset, pk=asset_pk, request=vr)
        ra.delete()
        if not vr.request_assets.exists():
            vr.status = VendorVerificationRequest.Status.CANCELLED
            vr.save()
            return Response({"detail": "Asset removed. Request was empty and has been cancelled."}, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminVendorRequestCancelView(APIView):
    """
    POST /api/admin/vendor-requests/{pk}/cancel/

    Cancel a DRAFT or SENT vendor request.
    """

    permission_classes = [IsAuthenticated, permission_required("vendor.request")]

    def post(self, request, pk):
        vr, err = _vendor_request_in_scope(pk, request.user)
        if err:
            return err
        cancellable = (
            VendorVerificationRequest.Status.DRAFT,
            VendorVerificationRequest.Status.SENT,
        )
        if vr.status not in cancellable:
            return Response(
                {"detail": f"Only DRAFT or SENT requests can be cancelled. Current status: {vr.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        vr.status = VendorVerificationRequest.Status.CANCELLED
        vr.save()
        return Response(VendorVerificationRequestSerializer(vr).data)
