"""
Vendor-facing views: work queue, request detail, per-asset responses, photo upload, submit, QR scan.

All views enforce vendor ownership — a user can only access requests assigned to their vendor.
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.permissions import permission_required
from vendors.models import (
    VendorRequestAssetPhoto,
    VendorUserAssignment,
    VendorVerificationRequest,
    VendorVerificationRequestAsset,
)
from vendors.serializers import (
    VendorRequestAssetPhotoSerializer,
    VendorVerificationRequestAssetSerializer,
    VendorVerificationRequestDetailSerializer,
    VendorVerificationRequestSerializer,
)


def _get_vendor_for_user(user):
    """Return the active VendorOrganization for the given user, or None."""
    assignment = (
        VendorUserAssignment.objects.filter(user=user, is_active=True)
        .select_related("vendor")
        .first()
    )
    return assignment.vendor if assignment else None


# ---------------------------------------------------------------------------
# Vendor Work Queue
# ---------------------------------------------------------------------------

class VendorRequestListView(APIView):
    """List all vendor requests assigned to the logged-in user's vendor organization."""

    permission_classes = [IsAuthenticated, permission_required("vendor.respond")]

    def get(self, request):
        vendor = _get_vendor_for_user(request.user)
        if vendor is None:
            return Response(
                {"detail": "Your account is not linked to any vendor organization."},
                status=status.HTTP_403_FORBIDDEN,
            )
        qs = VendorVerificationRequest.objects.filter(
            vendor=vendor,
            status__in=[
                VendorVerificationRequest.Status.SENT,
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.SUBMITTED,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
                VendorVerificationRequest.Status.APPROVED,
            ],
        ).select_related("vendor", "requested_by").order_by("-created_at")
        req_status = request.query_params.get("status")
        if req_status:
            qs = qs.filter(status=req_status)
        return Response(VendorVerificationRequestSerializer(qs, many=True).data)


# ---------------------------------------------------------------------------
# Vendor Request Detail
# ---------------------------------------------------------------------------

class VendorRequestDetailView(APIView):
    permission_classes = [IsAuthenticated, permission_required("vendor.respond")]

    def _get_request(self, user, pk):
        vendor = _get_vendor_for_user(user)
        if vendor is None:
            return None, Response(
                {"detail": "Your account is not linked to any vendor organization."},
                status=status.HTTP_403_FORBIDDEN,
            )
        vr = get_object_or_404(
            VendorVerificationRequest.objects.select_related("vendor", "requested_by"),
            pk=pk,
            vendor=vendor,
        )
        return vr, None

    def get(self, request, pk):
        vr, err = self._get_request(request.user, pk)
        if err:
            return err
        # Mark as in_progress when vendor first opens it
        if vr.status == VendorVerificationRequest.Status.SENT:
            vr.status = VendorVerificationRequest.Status.IN_PROGRESS
            vr.save(update_fields=["status"])
        return Response(
            VendorVerificationRequestDetailSerializer(vr, context={"request": request}).data
        )


# ---------------------------------------------------------------------------
# Vendor: per-asset response
# ---------------------------------------------------------------------------

class VendorRequestAssetUpdateView(APIView):
    """Vendor updates their response for a single asset."""

    permission_classes = [IsAuthenticated, permission_required("vendor.respond")]

    def patch(self, request, pk, asset_pk):
        vendor = _get_vendor_for_user(request.user)
        if vendor is None:
            return Response({"detail": "Not linked to a vendor."}, status=status.HTTP_403_FORBIDDEN)

        vr = get_object_or_404(
            VendorVerificationRequest,
            pk=pk,
            vendor=vendor,
            status__in=[
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
            ],
        )
        ra = get_object_or_404(VendorVerificationRequestAsset, pk=asset_pk, request=vr)

        # If correction requested, only correction-flagged assets are editable
        if vr.status == VendorVerificationRequest.Status.CORRECTION_REQUESTED:
            if ra.admin_decision != VendorVerificationRequestAsset.AdminDecision.CORRECTION_REQUIRED:
                return Response(
                    {"detail": "Only assets marked for correction can be updated."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        allowed = {"response_status", "response_notes", "observed_location_id"}
        for field in allowed:
            if field in request.data:
                setattr(ra, field, request.data[field] or None)

        response_status_val = request.data.get("response_status")
        if response_status_val in VendorVerificationRequestAsset.ResponseStatus.values:
            ra.response_status = response_status_val
            ra.responded_at = timezone.now()
            # Reset admin decision when vendor re-responds
            ra.admin_decision = VendorVerificationRequestAsset.AdminDecision.PENDING_REVIEW

        ra.save()
        return Response(VendorVerificationRequestAssetSerializer(ra, context={"request": request}).data)


# ---------------------------------------------------------------------------
# Vendor: photo upload for an asset
# ---------------------------------------------------------------------------

class VendorRequestAssetPhotoUploadView(APIView):
    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated, permission_required("vendor.respond")]

    def post(self, request, pk, asset_pk):
        vendor = _get_vendor_for_user(request.user)
        if vendor is None:
            return Response({"detail": "Not linked to a vendor."}, status=status.HTTP_403_FORBIDDEN)

        vr = get_object_or_404(
            VendorVerificationRequest,
            pk=pk,
            vendor=vendor,
            status__in=[
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
            ],
        )
        ra = get_object_or_404(VendorVerificationRequestAsset, pk=asset_pk, request=vr)

        # Mirror the update-view lock: during correction cycles only correction-flagged assets accept new photos
        if vr.status == VendorVerificationRequest.Status.CORRECTION_REQUESTED:
            if ra.admin_decision != VendorVerificationRequestAsset.AdminDecision.CORRECTION_REQUIRED:
                return Response(
                    {"detail": "Only assets marked for correction can have photos added."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        image = request.FILES.get("image")
        if not image:
            return Response({"image": ["No file uploaded."]}, status=status.HTTP_400_BAD_REQUEST)

        photo = VendorRequestAssetPhoto.objects.create(request_asset=ra, image=image)
        return Response(
            VendorRequestAssetPhotoSerializer(photo, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Vendor: submit the whole request
# ---------------------------------------------------------------------------

class VendorRequestSubmitView(APIView):
    permission_classes = [IsAuthenticated, permission_required("vendor.respond")]

    def post(self, request, pk):
        vendor = _get_vendor_for_user(request.user)
        if vendor is None:
            return Response({"detail": "Not linked to a vendor."}, status=status.HTTP_403_FORBIDDEN)

        vr = get_object_or_404(
            VendorVerificationRequest,
            pk=pk,
            vendor=vendor,
            status__in=[
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
            ],
        )

        # Ensure all assets (or all correction-flagged assets) have responses
        if vr.status == VendorVerificationRequest.Status.IN_PROGRESS:
            pending = vr.request_assets.filter(
                response_status=VendorVerificationRequestAsset.ResponseStatus.PENDING
            ).count()
            if pending:
                return Response(
                    {"detail": f"{pending} asset(s) still have no response. Respond to all assets before submitting."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:  # CORRECTION_REQUESTED — only correction-flagged assets must be responded
            pending_corrections = vr.request_assets.filter(
                admin_decision=VendorVerificationRequestAsset.AdminDecision.CORRECTION_REQUIRED,
                response_status=VendorVerificationRequestAsset.ResponseStatus.PENDING,
            ).count()
            if pending_corrections:
                return Response(
                    {"detail": f"{pending_corrections} correction-flagged asset(s) still have no response."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        vr.status = VendorVerificationRequest.Status.SUBMITTED
        vr.submitted_at = timezone.now()
        vr.review_notes = None  # clear old review notes on resubmission
        vr.save()
        return Response(VendorVerificationRequestSerializer(vr).data)


# ---------------------------------------------------------------------------
# Vendor: global scan — search across ALL of the vendor's active requests
# ---------------------------------------------------------------------------

class VendorGlobalScanView(APIView):
    """
    POST /api/vendor/requests/scan/
    Body: { qr_uid: "..." } or { asset_id: "AV-..." }

    Searches across ALL of the vendor's active requests (sent / in_progress /
    correction_requested) and returns routing info so the frontend can navigate
    directly to the right request + asset.
    """

    permission_classes = [IsAuthenticated, permission_required("vendor.respond")]

    def post(self, request):
        vendor = _get_vendor_for_user(request.user)
        if vendor is None:
            return Response({"detail": "Not linked to a vendor."}, status=status.HTTP_403_FORBIDDEN)

        qr_uid = request.data.get("qr_uid")
        asset_id = request.data.get("asset_id")

        if not qr_uid and not asset_id:
            return Response(
                {"detail": "Provide qr_uid or asset_id in request body."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from assets.models import Asset

        asset = None
        if qr_uid:
            asset = Asset.objects.filter(qr_uid=qr_uid).first()
        elif asset_id:
            asset = Asset.objects.filter(asset_id=asset_id).first()

        if asset is None:
            return Response(
                {"matched": False, "in_package": False, "detail": "Asset not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Check active (workable) requests ──────────────────────────────
        ACTIVE_STATUSES = [
            VendorVerificationRequest.Status.SENT,
            VendorVerificationRequest.Status.IN_PROGRESS,
            VendorVerificationRequest.Status.CORRECTION_REQUESTED,
        ]
        ra = (
            VendorVerificationRequestAsset.objects
            .filter(asset=asset, request__vendor=vendor, request__status__in=ACTIVE_STATUSES)
            .select_related("request")
            .first()
        )
        if ra:
            vr = ra.request
            editable = vr.status in [
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
            ]
            return Response({
                "matched": True,
                "in_package": True,
                "request_id": str(vr.id),
                "request_reference": vr.reference_code,
                "request_asset_id": str(ra.id),
                "asset_id": asset.asset_id,
                "asset_name": asset.name,
                "status": vr.status,
                "editable": editable,
            })

        # ── Check approved / locked requests ──────────────────────────────
        locked_ra = (
            VendorVerificationRequestAsset.objects
            .filter(
                asset=asset,
                request__vendor=vendor,
                request__status=VendorVerificationRequest.Status.APPROVED,
            )
            .select_related("request")
            .first()
        )
        if locked_ra:
            vr = locked_ra.request
            return Response({
                "matched": True,
                "in_package": False,
                "detail": (
                    f"This asset is in request {vr.reference_code} "
                    "which has already been approved and is locked."
                ),
                "request_id": str(vr.id),
                "request_reference": vr.reference_code,
            })

        # ── Not in any of this vendor's requests ──────────────────────────
        return Response({
            "matched": False,
            "in_package": False,
            "detail": "This asset is not assigned to any of your active verification requests.",
        })


# ---------------------------------------------------------------------------
# Vendor: QR scan validation (per-request)
# ---------------------------------------------------------------------------

class VendorRequestScanView(APIView):
    """Validate that a scanned asset (by qr_uid) belongs to the vendor's active request."""

    permission_classes = [IsAuthenticated, permission_required("vendor.respond")]

    def get(self, request, pk):
        vendor = _get_vendor_for_user(request.user)
        if vendor is None:
            return Response({"detail": "Not linked to a vendor."}, status=status.HTTP_403_FORBIDDEN)

        vr = get_object_or_404(
            VendorVerificationRequest,
            pk=pk,
            vendor=vendor,
            status__in=[
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
            ],
        )

        qr_uid = request.query_params.get("qr_uid")
        asset_id = request.query_params.get("asset_id")

        if not qr_uid and not asset_id:
            return Response(
                {"detail": "Provide qr_uid or asset_id query parameter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from assets.models import Asset

        asset = None
        if qr_uid:
            asset = Asset.objects.filter(qr_uid=qr_uid).first()
        elif asset_id:
            asset = Asset.objects.filter(asset_id=asset_id).first()

        if asset is None:
            return Response({"detail": "Asset not found.", "in_package": False}, status=status.HTTP_404_NOT_FOUND)

        ra = vr.request_assets.filter(asset=asset).first()
        if ra is None:
            return Response(
                {
                    "detail": "This asset is not part of your current verification package.",
                    "in_package": False,
                    "asset_id": asset.asset_id,
                    "asset_name": asset.name,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "in_package": True,
                "request_asset_id": str(ra.id),
                "asset_id": asset.asset_id,
                "asset_name": asset.name,
                "response_status": ra.response_status,
                "admin_decision": ra.admin_decision,
            }
        )
