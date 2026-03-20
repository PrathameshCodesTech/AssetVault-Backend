import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.helpers import get_user_scope
from access.permissions import permission_required
from accounts.models import OtpChallenge, User
from accounts.services.email_service import send_tracked_email
from accounts.services.otp_service import (
    check_resend_throttle,
    create_otp_challenge,
    mark_otp_consumed,
    verify_otp,
)
from assets.models import Asset
from verification.models import (
    AssetVerificationResponse,
    VerificationAssetPhoto,
    VerificationCycle,
    VerificationDeclaration,
    VerificationIssue,
    VerificationRequest,
    VerificationRequestAsset,
)
from verification.serializers import (
    CreateVerificationRequestSerializer,
    PublicSubmitSerializer,
    PublicVerificationRequestSerializer,
    VerificationCycleSerializer,
    VerificationRequestDetailSerializer,
    VerificationRequestSerializer,
)
from verification.services.request_service import (
    cancel_verification_request,
    create_verification_request,
    resend_verification_request,
    snapshot_request_assets,
    submit_verification_request,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_RESENDABLE_STATUSES = {
    VerificationRequest.Status.PENDING,
    VerificationRequest.Status.OPENED,
}


def _get_existing_active_vr(cycle, employee):
    """Return the most recent active VerificationRequest for this employee+cycle, or None."""
    return (
        VerificationRequest.objects.filter(
            cycle=cycle,
            employee=employee,
            status__in=list(VerificationRequest.ACTIVE_STATUSES),
        )
        .order_by("-created_at")
        .first()
    )


def _dispatch_magic_link_email(vr, employee, cycle):
    """Send the verification magic-link email. Returns (record, sent_ok).

    Employee access is link-based — no OTP step required.
    """
    frontend_base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:8081")
    verify_url = f"{frontend_base}/verify/{vr.public_token}"
    return send_tracked_email(
        to_email=employee.email,
        subject="Please verify your assigned assets",
        body=(
            f"Hi {employee.get_full_name() or employee.email},\n\n"
            f"You have been asked to verify your assigned assets for cycle '{cycle.name}'.\n\n"
            f"Click the link below to review and confirm your assets:\n{verify_url}\n\n"
            f"This link is unique to you — clicking it gives you direct access to your verification. "
            f"Do not share it.\n\n"
            f"If you were not expecting this, please ignore this message."
        ),
        template_code="verification_magic_link",
        related_object_type="VerificationRequest",
        related_object_id=str(vr.pk),
    )


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------


class VerificationCycleListView(APIView):
    """GET /api/verification/cycles — list verification cycles."""

    permission_classes = [IsAuthenticated, permission_required("verification.request")]

    def get(self, request):
        status_param = request.query_params.get("status")
        if status_param:
            qs = VerificationCycle.objects.filter(status=status_param)
        else:
            qs = VerificationCycle.objects.filter(status=VerificationCycle.Status.ACTIVE)
        qs = qs.order_by("-start_date", "-created_at")
        return Response(VerificationCycleSerializer(qs, many=True).data)


class VerificationRequestListCreateView(APIView):
    """
    GET  /api/verification/requests — list verification requests
    POST /api/verification/requests — create a new verification request
    """

    permission_classes = [IsAuthenticated, permission_required("verification.request")]

    def get(self, request):
        qs = VerificationRequest.objects.select_related(
            "cycle", "employee"
        ).order_by("-created_at")

        scope = get_user_scope(request.user)
        if not scope["is_global"] and scope["location_ids"]:
            qs = qs.filter(location_scope_id__in=scope["location_ids"])
        elif not scope["is_global"] and not scope["location_ids"]:
            qs = qs.none()

        cycle_id = request.query_params.get("cycle_id")
        if cycle_id:
            qs = qs.filter(cycle_id=cycle_id)

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        employee_id = request.query_params.get("employee_id")
        if employee_id:
            qs = qs.filter(employee_id=employee_id)

        from rest_framework.pagination import PageNumberPagination

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 25))
        page = paginator.paginate_queryset(qs, request)
        serializer = VerificationRequestSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        from access.helpers import location_in_scope

        serializer = CreateVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            cycle = VerificationCycle.objects.get(pk=data["cycle_id"])
        except VerificationCycle.DoesNotExist:
            return Response(
                {"detail": "Cycle not found."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            employee = User.objects.get(pk=data["employee_id"])
        except User.DoesNotExist:
            return Response(
                {"detail": "Employee not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # Validate explicit asset list
        asset_ids = data["asset_ids"]
        if len(asset_ids) != len(set(asset_ids)):
            return Response(
                {"detail": "Duplicate asset IDs in request."}, status=status.HTTP_400_BAD_REQUEST
            )

        assets = list(
            Asset.objects.filter(pk__in=asset_ids)
            .select_related("category", "current_location", "assigned_to")
        )
        if len(assets) != len(asset_ids):
            found_ids = {str(a.pk) for a in assets}
            missing = [str(aid) for aid in asset_ids if str(aid) not in found_ids]
            return Response(
                {"detail": f"Asset(s) not found: {', '.join(missing[:5])}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Verify all assets belong to the same employee
        for a in assets:
            if str(a.assigned_to_id) != str(employee.pk):
                return Response(
                    {
                        "detail": (
                            f"Asset '{a.asset_id}' is not assigned to employee '{employee.email}'. "
                            f"All assets in one request must belong to the same employee."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        force_resend = str(request.data.get("force_resend", "false")).lower() in ("true", "1")

        # Cross-flow guard: block if any asset is in an active vendor verification request
        try:
            from vendors.models import (
                VendorVerificationRequest,
                VendorVerificationRequestAsset,
            )
            _vendor_active = [
                VendorVerificationRequest.Status.SENT,
                VendorVerificationRequest.Status.IN_PROGRESS,
                VendorVerificationRequest.Status.SUBMITTED,
                VendorVerificationRequest.Status.CORRECTION_REQUESTED,
            ]
            for a in assets:
                vra = (
                    VendorVerificationRequestAsset.objects
                    .filter(asset=a, request__status__in=_vendor_active)
                    .select_related("request")
                    .first()
                )
                if vra:
                    return Response(
                        {
                            "detail": (
                                f"Asset '{a.asset_id}' is part of active vendor request "
                                f"'{vra.request.reference_code}'. Resolve or close that "
                                f"request before sending a new employee verification."
                            ),
                            "conflict_type": "active_vendor_request",
                            "request_reference": vra.request.reference_code,
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
        except ImportError:
            pass

        # Asset-level duplicate guard: block if any asset is already in an active
        # employee verification request (any cycle, any status in ACTIVE_STATUSES).
        # This prevents the same asset appearing in two concurrent active requests
        # across different cycles. The force_reassign path in AssetAssignView evicts
        # the asset from its old request before reassigning, so after a reassignment
        # this guard will no longer fire for the new owner.
        for a in assets:
            existing_vra = (
                VerificationRequestAsset.objects
                .filter(
                    asset=a,
                    verification_request__status__in=list(VerificationRequest.ACTIVE_STATUSES),
                )
                .select_related("verification_request", "verification_request__cycle", "verification_request__employee")
                .first()
            )
            if existing_vra:
                existing_vr = existing_vra.verification_request
                # Allow if it's the same cycle+employee (handled by _get_existing_active_vr below)
                # so only surface a distinct conflict for cross-cycle duplicates
                if not (existing_vr.cycle_id == cycle.pk and existing_vr.employee_id == employee.pk):
                    return Response(
                        {
                            "detail": (
                                f"Asset '{a.asset_id}' is already in active verification request "
                                f"'{existing_vr.reference_code}' (cycle '{existing_vr.cycle.code}') "
                                f"for '{existing_vr.employee.email}'. "
                                f"An asset cannot be in two active employee requests simultaneously."
                            ),
                            "conflict_type": "asset_in_active_request",
                            "request_reference": existing_vr.reference_code,
                            "employee_email": existing_vr.employee.email,
                            "cycle_code": existing_vr.cycle.code,
                            "asset_id": a.asset_id,
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

        # Cycle-verified guard: block if any asset is already admin-approved in this cycle
        # unless the admin explicitly overrides with force_resend=true
        if not force_resend:
            for a in assets:
                approved = AssetVerificationResponse.objects.filter(
                    request_asset__verification_request__cycle=cycle,
                    request_asset__asset=a,
                    admin_review_status=AssetVerificationResponse.AdminReviewStatus.APPROVED,
                ).exists()
                if approved:
                    return Response(
                        {
                            "detail": (
                                f"Asset '{a.asset_id}' is already approved in cycle "
                                f"'{cycle.code}'. Use force_resend=true to re-send anyway."
                            ),
                            "conflict_type": "already_verified",
                            "asset_id": a.asset_id,
                            "cycle_code": cycle.code,
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

        ref_code = data.get("reference_code") or f"VER-{cycle.code}-{secrets.token_hex(4).upper()}"

        # Validate all assets are in scope for the sender
        for a in assets:
            if a.current_location_id and not location_in_scope(a.current_location_id, request.user):
                return Response(
                    {"detail": f"Asset '{a.asset_id}' is outside your allowed location scope."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Resolve location_scope: explicit, auto-derived, or null (global)
        from locations.models import LocationClosure, LocationNode

        location_scope = None
        if data.get("location_scope_id"):
            try:
                location_scope = LocationNode.objects.get(
                    pk=data["location_scope_id"]
                )
            except LocationNode.DoesNotExist:
                return Response(
                    {"detail": "Location scope not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if not location_in_scope(location_scope.pk, request.user):
                return Response(
                    {"detail": "Location scope is outside your allowed subtree."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Every asset must be inside the provided location_scope subtree
            scope_desc_ids = set(
                LocationClosure.objects.filter(ancestor=location_scope)
                .values_list("descendant_id", flat=True)
            )
            for a in assets:
                if a.current_location_id and a.current_location_id not in scope_desc_ids:
                    return Response(
                        {
                            "detail": (
                                f"Asset '{a.asset_id}' (location '{a.current_location.name if a.current_location else 'N/A'}') "
                                f"is outside the supplied location scope."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        scope = get_user_scope(request.user)
        if not scope["is_global"] and location_scope is None:
            # Auto-derive: find the shallowest role-assignment location
            # that covers all selected assets.
            from access.models import UserRoleAssignment

            root_loc_ids = list(
                UserRoleAssignment.objects.filter(
                    user=request.user, is_active=True, location__isnull=False
                ).values_list("location_id", flat=True)
            )
            asset_loc_ids = {a.current_location_id for a in assets if a.current_location_id}
            chosen = None
            for rl_id in root_loc_ids:
                desc_ids = set(
                    LocationClosure.objects.filter(ancestor_id=rl_id)
                    .values_list("descendant_id", flat=True)
                )
                if asset_loc_ids.issubset(desc_ids):
                    chosen = rl_id
                    break
            if chosen is None:
                return Response(
                    {"detail": "Selected assets span multiple location scopes. Please narrow your selection."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            location_scope = LocationNode.objects.get(pk=chosen)

        # Block if active request already exists for this employee+cycle
        existing_vr = _get_existing_active_vr(cycle, employee)
        if existing_vr is not None:
            return Response(
                {
                    "detail": (
                        f"Employee '{employee.email}' already has an active verification request "
                        f"in cycle '{cycle.code}' (status: {existing_vr.status}). "
                        f"Complete or cancel it before sending another."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            vr = create_verification_request(
                cycle=cycle,
                employee=employee,
                requested_by=request.user,
                location_scope=location_scope,
                reference_code=ref_code,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        snapshot_request_assets(vr, assets)

        _record, sent_ok = _dispatch_magic_link_email(vr, employee, cycle)
        if not sent_ok:
            vr.delete()
            return Response(
                {"detail": "Unable to send verification email. Please try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        vr.sent_at = timezone.now()
        vr.save(update_fields=["sent_at", "updated_at"])

        result = VerificationRequestDetailSerializer(vr).data
        return Response(result, status=status.HTTP_201_CREATED)


def _vr_in_scope(vr, user):
    """Check if a VerificationRequest is within the user's location scope.

    A scoped admin can only access VRs whose location_scope is inside their
    subtree. A VR with ``location_scope=NULL`` is a global request — only
    global admins may access it.
    """
    scope = get_user_scope(user)
    if scope["is_global"]:
        return True
    if not scope["location_ids"]:
        return False
    if vr.location_scope_id is None:
        return False
    return vr.location_scope_id in scope["location_ids"]


class VerificationRequestDetailView(RetrieveAPIView):
    """GET /api/verification/requests/{id}"""

    permission_classes = [IsAuthenticated, permission_required("verification.request")]
    serializer_class = VerificationRequestDetailSerializer

    def get_queryset(self):
        qs = VerificationRequest.objects.select_related(
            "cycle", "employee"
        ).prefetch_related(
            "request_assets",
            "request_assets__photos",
            "request_assets__response",
        )

        scope = get_user_scope(self.request.user)
        if not scope["is_global"] and scope["location_ids"]:
            qs = qs.filter(location_scope_id__in=scope["location_ids"])
        elif not scope["is_global"] and not scope["location_ids"]:
            qs = qs.none()

        return qs


class ResendVerificationRequestView(APIView):
    """POST /api/verification/requests/{id}/resend"""

    permission_classes = [IsAuthenticated, permission_required("verification.request")]

    def post(self, request, pk):
        try:
            vr = VerificationRequest.objects.get(pk=pk)
        except VerificationRequest.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _vr_in_scope(vr, request.user):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            resend_verification_request(vr, requested_by=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Resent."})


class CancelVerificationRequestView(APIView):
    """POST /api/verification/requests/{id}/cancel"""

    permission_classes = [IsAuthenticated, permission_required("verification.request")]

    def post(self, request, pk):
        try:
            vr = VerificationRequest.objects.get(pk=pk)
        except VerificationRequest.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _vr_in_scope(vr, request.user):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            cancel_verification_request(vr, cancelled_by=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Cancelled."})


class AdminReviewVerificationView(APIView):
    """POST /api/verification/requests/{id}/review — per-asset approve/correction_required."""

    permission_classes = [IsAuthenticated, permission_required("verification.request")]

    def post(self, request, pk):
        from verification.serializers import AdminReviewActionSerializer

        serializer = AdminReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        review_note = data.get("review_note", "")
        asset_reviews = data["asset_reviews"]

        try:
            vr = VerificationRequest.objects.select_related("cycle", "employee").get(pk=pk)
        except VerificationRequest.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _vr_in_scope(vr, request.user):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if vr.status != VerificationRequest.Status.SUBMITTED:
            return Response(
                {"detail": f"Cannot review a request with status '{vr.status}'. Only submitted requests can be reviewed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate all supplied request_asset_ids belong to this VR
        vr_asset_ids = set(str(ra.pk) for ra in vr.request_assets.all())
        for item in asset_reviews:
            if str(item["request_asset_id"]) not in vr_asset_ids:
                return Response(
                    {"detail": f"request_asset_id {item['request_asset_id']} does not belong to this verification request."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        reviewed_asset_ids = {str(item["request_asset_id"]) for item in asset_reviews}
        missing_reviews = vr_asset_ids - reviewed_asset_ids
        if missing_reviews:
            return Response(
                {
                    "detail": (
                        "Every asset in the verification request must be reviewed before finalizing. "
                        f"Missing decisions for {len(missing_reviews)} asset(s)."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Apply per-asset decisions
        now = timezone.now()
        for item in asset_reviews:
            AssetVerificationResponse.objects.filter(
                request_asset_id=item["request_asset_id"]
            ).update(
                admin_review_status=item["decision"],
                admin_review_note=item.get("note") or "",
                admin_reviewed_at=now,
                admin_reviewed_by=request.user,
            )

        # Derive request-level status from all per-asset decisions
        all_responses = AssetVerificationResponse.objects.filter(
            request_asset__verification_request=vr
        )
        has_correction = all_responses.filter(
            admin_review_status=AssetVerificationResponse.AdminReviewStatus.CORRECTION_REQUIRED
        ).exists()

        vr.review_notes = review_note

        if has_correction:
            vr.status = VerificationRequest.Status.CORRECTION_REQUESTED
            vr.public_token = secrets.token_urlsafe(32)
            vr.save(update_fields=["status", "review_notes", "public_token", "updated_at"])

            approved_count = all_responses.filter(
                admin_review_status=AssetVerificationResponse.AdminReviewStatus.APPROVED
            ).count()
            correction_count = all_responses.filter(
                admin_review_status=AssetVerificationResponse.AdminReviewStatus.CORRECTION_REQUIRED
            ).count()

            email_sent = _dispatch_correction_email(
                vr, vr.employee, vr.cycle, approved_count, correction_count, review_note
            )
            msg = "Correction requested. Employee has been notified."
            if not email_sent:
                msg = "Correction requested. Notification email could not be sent; please share the link manually."
            return Response({"detail": msg, "status": vr.status})

        else:
            vr.status = VerificationRequest.Status.APPROVED
            vr.save(update_fields=["status", "review_notes", "updated_at"])
            return Response({"detail": "Verification approved.", "status": vr.status})


def _dispatch_correction_email(vr, employee, cycle, approved_count, correction_count, review_note):
    """Send correction-request email with per-asset counts. Returns True if sent."""
    frontend_base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:8081")
    verify_url = f"{frontend_base}/verify/{vr.public_token}"
    note_section = f"\n\nAdmin note:\n{review_note}" if review_note else ""
    _record, sent_ok = send_tracked_email(
        to_email=employee.email,
        subject=f"Action required: asset verification correction — {cycle.name}",
        body=(
            f"Hi {employee.get_full_name() or employee.email},\n\n"
            f"Your asset verification for cycle '{cycle.name}' has been reviewed.{note_section}\n\n"
            f"Results:\n"
            f"  • {approved_count} asset(s) approved\n"
            f"  • {correction_count} asset(s) require correction\n\n"
            f"Please use the link below to review the flagged asset(s) and resubmit:\n{verify_url}\n\n"
            f"Only the asset(s) requiring correction need to be updated. "
            f"Already-approved assets are locked.\n\n"
            f"If you have questions, please contact your administrator."
        ),
        template_code="verification_correction",
        related_object_type="VerificationRequest",
        related_object_id=str(vr.pk),
    )
    return sent_ok


# ---------------------------------------------------------------------------
# Public portal views
# ---------------------------------------------------------------------------


class PublicVerificationRequestView(APIView):
    """GET /api/verification/public/{token} — public portal page data."""

    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            vr = VerificationRequest.objects.select_related(
                "cycle", "employee"
            ).get(public_token=token)
        except VerificationRequest.DoesNotExist:
            return Response(
                {"detail": "Invalid or expired link."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Mark as opened
        if vr.status == VerificationRequest.Status.PENDING:
            vr.status = VerificationRequest.Status.OPENED
            vr.opened_at = timezone.now()
            vr.save(update_fields=["status", "opened_at", "updated_at"])

        serializer = PublicVerificationRequestSerializer(vr, context={"request": request})
        return Response(serializer.data)


class PublicSendOtpView(APIView):
    """POST /api/verification/public/{token}/otp/send"""

    permission_classes = [AllowAny]

    def post(self, request, token):
        try:
            vr = VerificationRequest.objects.select_related("employee").get(
                public_token=token
            )
        except VerificationRequest.DoesNotExist:
            return Response(
                {"detail": "Invalid link."}, status=status.HTTP_404_NOT_FOUND
            )

        otp_allowed = {
            VerificationRequest.Status.PENDING,
            VerificationRequest.Status.OPENED,
            VerificationRequest.Status.REJECTED,
            VerificationRequest.Status.CORRECTION_REQUESTED,
        }
        if vr.status not in otp_allowed:
            return Response(
                {"detail": f"Request is in '{vr.status}' state."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = vr.employee.email
        try:
            check_resend_throttle(
                email, OtpChallenge.Purpose.EMPLOYEE_VERIFICATION
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        challenge, raw_code = create_otp_challenge(
            email=email,
            purpose=OtpChallenge.Purpose.EMPLOYEE_VERIFICATION,
            user=vr.employee,
            related_object_type="VerificationRequest",
            related_object_id=str(vr.pk),
        )

        _record, sent_ok = send_tracked_email(
            to_email=email,
            subject="Your asset verification code",
            body=(
                f"Your verification code is: {raw_code}\n\n"
                f"This code expires in 10 minutes.\n"
                f"If you did not request this, please ignore this message."
            ),
            template_code="verification_otp",
            related_object_type="VerificationRequest",
            related_object_id=str(vr.pk),
        )

        if not sent_ok:
            challenge.delete()
            return Response(
                {"detail": "Unable to send verification email. Please try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        resp = {"challenge_id": str(challenge.pk)}
        if settings.DEBUG:
            resp["debug_otp"] = raw_code
        return Response(resp)


class PublicVerifyOtpView(APIView):
    """POST /api/verification/public/{token}/otp/verify"""

    permission_classes = [AllowAny]

    def post(self, request, token):
        try:
            vr = VerificationRequest.objects.get(public_token=token)
        except VerificationRequest.DoesNotExist:
            return Response(
                {"detail": "Invalid link."}, status=status.HTTP_404_NOT_FOUND
            )

        challenge_id = request.data.get("challenge_id")
        otp = request.data.get("otp")
        if not challenge_id or not otp:
            return Response(
                {"detail": "challenge_id and otp are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            challenge = OtpChallenge.objects.get(
                pk=challenge_id,
                purpose=OtpChallenge.Purpose.EMPLOYEE_VERIFICATION,
                related_object_type="VerificationRequest",
                related_object_id=str(vr.pk),
            )
        except OtpChallenge.DoesNotExist:
            return Response(
                {"detail": "Invalid challenge."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            verify_otp(challenge, otp)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        mark_otp_consumed(challenge)

        vr.status = VerificationRequest.Status.OTP_VERIFIED
        vr.otp_verified_at = timezone.now()
        vr.save(update_fields=["status", "otp_verified_at", "updated_at"])

        return Response({"detail": "OTP verified.", "status": vr.status})


_EMPLOYEE_ACTIVE_STATUSES = {
    VerificationRequest.Status.OPENED,
    VerificationRequest.Status.CORRECTION_REQUESTED,
}


class PublicUploadAssetPhotoView(APIView):
    """POST /api/verification/public/{token}/assets/{asset_id}/photos/

    Accepts a multipart file field named "photo". Link-based access — no OTP required.
    Maximum 3 photos per VerificationRequestAsset.
    """

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, token, asset_id):
        try:
            vr = VerificationRequest.objects.get(public_token=token)
        except VerificationRequest.DoesNotExist:
            return Response({"detail": "Invalid link."}, status=status.HTTP_404_NOT_FOUND)

        if vr.status not in _EMPLOYEE_ACTIVE_STATUSES:
            return Response(
                {"detail": f"This link is not active for photo upload. Status: {vr.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ra = VerificationRequestAsset.objects.get(pk=asset_id, verification_request=vr)
        except VerificationRequestAsset.DoesNotExist:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        existing_response = AssetVerificationResponse.objects.filter(request_asset=ra).first()
        if (
            existing_response
            and existing_response.admin_review_status
            == AssetVerificationResponse.AdminReviewStatus.APPROVED
        ):
            return Response(
                {"detail": "This asset has already been approved and is locked."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if VerificationAssetPhoto.objects.filter(request_asset=ra).count() >= 3:
            return Response(
                {"detail": "Maximum of 3 photos per asset."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        photo_file = request.FILES.get("photo")
        if not photo_file:
            return Response({"detail": "No photo file provided."}, status=status.HTTP_400_BAD_REQUEST)

        if photo_file.size > 10 * 1024 * 1024:  # 10 MB
            return Response({"detail": "Photo must be under 10 MB."}, status=status.HTTP_400_BAD_REQUEST)

        photo = VerificationAssetPhoto.objects.create(request_asset=ra, image=photo_file)

        from verification.serializers import VerificationAssetPhotoSerializer
        serializer = VerificationAssetPhotoSerializer(photo, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PublicSubmitView(APIView):
    """POST /api/verification/public/{token}/submit — submit asset verification."""

    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request, token):
        try:
            vr = VerificationRequest.objects.select_related(
                "cycle", "employee"
            ).get(public_token=token)
        except VerificationRequest.DoesNotExist:
            return Response(
                {"detail": "Invalid link."}, status=status.HTTP_404_NOT_FOUND
            )

        if vr.status not in _EMPLOYEE_ACTIVE_STATUSES:
            return Response(
                {"detail": f"This link is not active for submission. Status: {vr.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PublicSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Process each asset response — skip already-approved assets (correction cycle guard)
        for resp_data in data["responses"]:
            try:
                ra = VerificationRequestAsset.objects.get(
                    pk=resp_data["request_asset_id"],
                    verification_request=vr,
                )
            except VerificationRequestAsset.DoesNotExist:
                continue

            # Do not overwrite an admin-approved response
            existing = AssetVerificationResponse.objects.filter(request_asset=ra).first()
            if existing and existing.admin_review_status == AssetVerificationResponse.AdminReviewStatus.APPROVED:
                continue

            avr, _ = AssetVerificationResponse.objects.update_or_create(
                request_asset=ra,
                defaults={
                    "response": resp_data["response"],
                    "remarks": resp_data.get("remarks", ""),
                    "responded_at": timezone.now(),
                },
            )

            # Handle issue
            if resp_data["response"] == AssetVerificationResponse.Response.ISSUE_REPORTED:
                issue_type = resp_data.get("issue_type") or VerificationIssue.IssueType.OTHER
                issue_desc = resp_data.get("issue_description") or "Issue reported"
                VerificationIssue.objects.update_or_create(
                    asset_response=avr,
                    defaults={
                        "issue_type": issue_type,
                        "description": issue_desc,
                    },
                )
                # If missing, update asset status
                if issue_type == VerificationIssue.IssueType.MISSING:
                    Asset.objects.filter(pk=ra.asset_id).update(
                        status=Asset.Status.MISSING
                    )
            else:
                # Remove issue if response changed to verified
                VerificationIssue.objects.filter(asset_response=avr).delete()

        # Create/update declaration (update_or_create for resubmissions)
        VerificationDeclaration.objects.update_or_create(
            verification_request=vr,
            defaults={
                "declared_by_name": data["declared_by_name"],
                "declared_by_email": data["declared_by_email"],
                "consent_text_version": data.get("consent_text_version", "1.0"),
                "consented_at": timezone.now(),
                "ip_address": self._get_client_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            },
        )

        # Submit
        try:
            submit_verification_request(vr)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            PublicVerificationRequestSerializer(vr, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def _get_client_ip(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


# ---------------------------------------------------------------------------
# Public: employee report missing/misplaced asset
# ---------------------------------------------------------------------------


class PublicReportAssetView(APIView):
    """POST /api/verification/public/{token}/report-asset

    Allows the employee to report a missing, misplaced, or unlisted asset
    that is NOT part of their original verification request.
    Requires OTP_VERIFIED state — employee must re-verify OTP after rejection
    before adding reports.
    """

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    MAX_PHOTOS = 5
    MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

    def post(self, request, token):
        from verification.models import EmployeeAssetReport, EmployeeReportPhoto
        from verification.serializers import (
            CreateEmployeeAssetReportSerializer,
            EmployeeAssetReportSerializer,
        )

        try:
            vr = VerificationRequest.objects.get(public_token=token)
        except VerificationRequest.DoesNotExist:
            return Response(
                {"detail": "Invalid or expired link."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if vr.status not in _EMPLOYEE_ACTIVE_STATUSES:
            return Response(
                {"detail": f"This link is not active for reporting assets. Status: {vr.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        photos = request.FILES.getlist("photos")
        if len(photos) > self.MAX_PHOTOS:
            return Response(
                {"detail": f"Maximum of {self.MAX_PHOTOS} photos per report."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        for photo_file in photos:
            if photo_file.size > self.MAX_PHOTO_SIZE_BYTES:
                return Response(
                    {"detail": "Each photo must be under 10 MB."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = CreateEmployeeAssetReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        report = EmployeeAssetReport.objects.create(
            verification_request=vr,
            report_type=data["report_type"],
            asset_name=data["asset_name"],
            asset_id_if_known=data.get("asset_id_if_known") or None,
            serial_number=data.get("serial_number") or None,
            category_name=data.get("category_name") or None,
            location_description=data.get("location_description") or None,
            expected_location=data.get("expected_location") or None,
            remarks=data.get("remarks") or None,
        )

        for photo_file in photos:
            EmployeeReportPhoto.objects.create(report=report, image=photo_file)

        result = EmployeeAssetReportSerializer(report, context={"request": request}).data
        return Response(result, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Quick send: create a verification request directly from a registered asset
# ---------------------------------------------------------------------------


class QuickSendVerificationView(APIView):
    """
    POST /api/verification/requests/quick-send/

    Create a VerificationRequest for a single asset without requiring the
    caller to supply a cycle_id. Resolves to the most recently created
    active cycle automatically.

    Payload: { "asset_id": "<asset-uuid>" }

    Requirements:
      - asset must have assigned_to set
      - at least one active VerificationCycle must exist
    """

    permission_classes = [IsAuthenticated, permission_required("verification.request")]

    def post(self, request):
        import secrets as _secrets

        asset_id = request.data.get("asset_id")
        if not asset_id:
            return Response(
                {"detail": "asset_id is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            asset = Asset.objects.select_related(
                "assigned_to", "current_location", "category"
            ).get(pk=asset_id)
        except (Asset.DoesNotExist, Exception):
            return Response(
                {"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if not asset.assigned_to_id:
            return Response(
                {
                    "detail": (
                        "Asset has no assigned employee. "
                        "Assign an employee before sending a verification request."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        employee = asset.assigned_to

        cycle = (
            VerificationCycle.objects.filter(status=VerificationCycle.Status.ACTIVE)
            .order_by("-start_date", "-created_at")
            .first()
        )
        if not cycle:
            return Response(
                {
                    "detail": (
                        "No active verification cycle found. "
                        "Create and activate a cycle before sending requests."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Determine location scope from asset's current location.
        # Scoped admins must have the asset's location inside their allowed subtree.
        location_scope = None
        if asset.current_location_id:
            from access.helpers import location_in_scope
            from locations.models import LocationNode

            try:
                location_scope = LocationNode.objects.get(pk=asset.current_location_id)
            except LocationNode.DoesNotExist:
                location_scope = None

        scope = get_user_scope(request.user)
        if not scope["is_global"]:
            if location_scope is None:
                return Response(
                    {"detail": "Asset has no location. Scoped admins cannot send without a location."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not location_in_scope(location_scope.pk, request.user):
                return Response(
                    {"detail": "Asset is outside your allowed location scope."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Block if active request already exists for this employee+cycle
        existing_vr = _get_existing_active_vr(cycle, employee)
        if existing_vr is not None:
            return Response(
                {
                    "detail": (
                        f"Employee '{employee.email}' already has an active verification request "
                        f"in cycle '{cycle.code}' (status: {existing_vr.status}). "
                        f"Complete or cancel it before sending another."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ref_code = f"VER-{cycle.code}-{_secrets.token_hex(4).upper()}"
        try:
            vr = create_verification_request(
                cycle=cycle,
                employee=employee,
                requested_by=request.user,
                location_scope=location_scope,
                reference_code=ref_code,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        asset_qs = Asset.objects.filter(pk=asset.pk).select_related(
            "category", "current_location"
        )
        snapshot_request_assets(vr, asset_qs)

        _record, sent_ok = _dispatch_magic_link_email(vr, employee, cycle)
        if not sent_ok:
            vr.delete()
            return Response(
                {"detail": "Unable to send verification email. Please try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        vr.sent_at = timezone.now()
        vr.save(update_fields=["sent_at", "updated_at"])

        return Response(
            VerificationRequestDetailSerializer(vr).data,
            status=status.HTTP_201_CREATED,
        )


class SendSelectedAssetsVerificationView(APIView):
    """
    POST /api/verification/requests/send-selected

    Send a verification request for explicitly selected assets.
    Alias for VerificationRequestListCreateView.post with the same payload.

    Payload:
        cycle_id:          UUID
        employee_id:       UUID
        asset_ids:         [UUID, ...]
        location_scope_id: UUID (optional)
    """

    permission_classes = [IsAuthenticated, permission_required("verification.request")]

    def post(self, request):
        return VerificationRequestListCreateView().post(request)
