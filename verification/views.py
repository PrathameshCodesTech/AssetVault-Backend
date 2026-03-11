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
    """Send the verification magic-link email. Returns (record, sent_ok)."""
    frontend_base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:8081")
    verify_url = f"{frontend_base}/verify/{vr.public_token}"
    return send_tracked_email(
        to_email=employee.email,
        subject="Please verify your assigned assets",
        body=(
            f"Hi {employee.get_full_name() or employee.email},\n\n"
            f"You have been asked to verify your assigned assets for cycle '{cycle.name}'.\n\n"
            f"Click the link below to begin:\n{verify_url}\n\n"
            f"This link is unique to you. Do not share it.\n\n"
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

        ref_code = data.get("reference_code") or f"VER-{cycle.code}-{secrets.token_hex(4).upper()}"

        location_scope = None
        if data.get("location_scope_id"):
            from locations.models import LocationNode

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

        scope = get_user_scope(request.user)
        if not scope["is_global"] and location_scope is None:
            return Response(
                {"detail": "Scoped admins must supply a location_scope_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resend if an active request already exists for this employee+cycle
        existing_vr = _get_existing_active_vr(cycle, employee)
        if existing_vr is not None:
            if existing_vr.status not in _RESENDABLE_STATUSES:
                return Response(
                    {
                        "detail": (
                            f"Employee already has an active verification request "
                            f"(status: {existing_vr.status}). "
                            f"Wait for them to complete it or cancel it first."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            vr = resend_verification_request(existing_vr, requested_by=request.user)
            is_new = False
        else:
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

            # Snapshot assets assigned to the employee (within location scope if given)
            asset_qs = Asset.objects.filter(assigned_to=employee).select_related(
                "category", "current_location"
            )
            if location_scope:
                from locations.models import LocationClosure

                desc_ids = LocationClosure.objects.filter(
                    ancestor=location_scope
                ).values_list("descendant_id", flat=True)
                asset_qs = asset_qs.filter(current_location_id__in=desc_ids)

            snapshot_request_assets(vr, asset_qs)
            is_new = True

        _record, sent_ok = _dispatch_magic_link_email(vr, employee, cycle)
        if not sent_ok:
            if is_new:
                vr.delete()
            return Response(
                {"detail": "Unable to send verification email. Please try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if is_new:
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
        ).prefetch_related("request_assets", "request_assets__photos")

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

        if vr.status not in {
            VerificationRequest.Status.PENDING,
            VerificationRequest.Status.OPENED,
        }:
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


class PublicUploadAssetPhotoView(APIView):
    """POST /api/verification/public/{token}/assets/{asset_id}/photos/

    Accepts a multipart file field named "photo". Request must be in OTP_VERIFIED state.
    Maximum 3 photos per VerificationRequestAsset.
    """

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, token, asset_id):
        try:
            vr = VerificationRequest.objects.get(public_token=token)
        except VerificationRequest.DoesNotExist:
            return Response({"detail": "Invalid link."}, status=status.HTTP_404_NOT_FOUND)

        if vr.status != VerificationRequest.Status.OTP_VERIFIED:
            return Response(
                {"detail": f"Photos can only be uploaded after OTP verification. Current: {vr.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ra = VerificationRequestAsset.objects.get(pk=asset_id, verification_request=vr)
        except VerificationRequestAsset.DoesNotExist:
            return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

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

        if vr.status != VerificationRequest.Status.OTP_VERIFIED:
            return Response(
                {"detail": f"Request must be OTP verified. Current: {vr.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PublicSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Process each asset response
        for resp_data in data["responses"]:
            try:
                ra = VerificationRequestAsset.objects.get(
                    pk=resp_data["request_asset_id"],
                    verification_request=vr,
                )
            except VerificationRequestAsset.DoesNotExist:
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

        # Create declaration
        VerificationDeclaration.objects.create(
            verification_request=vr,
            declared_by_name=data["declared_by_name"],
            declared_by_email=data["declared_by_email"],
            consent_text_version=data.get("consent_text_version", "1.0"),
            consented_at=timezone.now(),
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
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

        # Resend if an active request already exists for this employee+cycle
        existing_vr = _get_existing_active_vr(cycle, employee)
        if existing_vr is not None:
            if existing_vr.status not in _RESENDABLE_STATUSES:
                return Response(
                    {
                        "detail": (
                            f"Employee already has an active verification request "
                            f"(status: {existing_vr.status}). "
                            f"Wait for them to complete it or cancel it first."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            vr = resend_verification_request(existing_vr, requested_by=request.user)
            is_new = False
        else:
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
            is_new = True

        _record, sent_ok = _dispatch_magic_link_email(vr, employee, cycle)
        if not sent_ok:
            if is_new:
                vr.delete()
            return Response(
                {"detail": "Unable to send verification email. Please try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if is_new:
            vr.sent_at = timezone.now()
            vr.save(update_fields=["sent_at", "updated_at"])

        return Response(
            VerificationRequestDetailSerializer(vr).data,
            status=status.HTTP_201_CREATED,
        )
