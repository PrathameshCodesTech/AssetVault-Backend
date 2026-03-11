import uuid as _uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.helpers import (
    filter_by_location_scope,
    get_user_permission_codes,
    location_in_scope,
)
from access.permissions import permission_required
from assets.models import Asset
from locations.models import LocationClosure, LocationNode
from submissions.models import FieldSubmission, FieldSubmissionPhoto
from submissions.serializers import (
    AdminReviewActionSerializer,
    ConvertToAssetSerializer,
    FieldSubmissionCreateSerializer,
    FieldSubmissionSerializer,
)
from submissions.services.submission_service import (
    approve_submission,
    convert_candidate_to_asset,
    create_submission,
    reject_submission,
    request_submission_correction,
)


def _parse_uuid(value, field_name="id"):
    """Validate *value* as a UUID. Returns the UUID object or None on failure."""
    if value is None:
        return None
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


_BAD_UUID = lambda name: Response(  # noqa: E731
    {"detail": f"Invalid {name} format — expected a UUID."},
    status=status.HTTP_400_BAD_REQUEST,
)


def _save_uploaded_photos(submission, request):
    """Persist uploaded photo files as FieldSubmissionPhoto rows."""
    photos = request.FILES.getlist("photos") or request.FILES.getlist("photo")
    for f in photos:
        FieldSubmissionPhoto.objects.create(
            submission=submission,
            image=f,
            image_type=FieldSubmissionPhoto.ImageType.ASSET_PHOTO,
        )


def _get_scoped_submission(pk, user):
    """Load a submission, returning None if it's outside the user's location scope."""
    try:
        submission = (
            FieldSubmission.objects.select_related(
                "asset", "location", "submitted_by"
            )
            .prefetch_related("photos", "reviews__reviewed_by")
            .get(pk=pk)
        )
    except (FieldSubmission.DoesNotExist, ValueError, DjangoValidationError):
        return None
    if not location_in_scope(submission.location_id, user):
        return None
    return submission


# ---------------------------------------------------------------------------
# Third-party endpoints (field operators)
# ---------------------------------------------------------------------------


class SubmissionListCreateView(APIView):
    """
    GET  — list submissions for the current user (requires auth only)
    POST — create a new field submission (requires submission.create, multipart supported)
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        perms = super().get_permissions()
        if self.request.method == "POST":
            perms.append(permission_required("submission.create")())
        return perms

    def get(self, request):
        qs = (
            FieldSubmission.objects.filter(submitted_by=request.user)
            .select_related("asset", "location", "submitted_by")
            .prefetch_related("photos", "reviews__reviewed_by")
            .order_by("-submitted_at")
        )

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        sub_type = request.query_params.get("type")
        if sub_type:
            qs = qs.filter(submission_type=sub_type)

        from rest_framework.pagination import PageNumberPagination

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 25))
        page = paginator.paginate_queryset(qs, request)
        serializer = FieldSubmissionSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = FieldSubmissionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            location = LocationNode.objects.get(pk=data["location_id"])
        except LocationNode.DoesNotExist:
            return Response(
                {"detail": "Location not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not location_in_scope(location.pk, request.user):
            return Response(
                {"detail": "Location is outside your allowed scope."},
                status=status.HTTP_403_FORBIDDEN,
            )

        asset = None
        if data.get("asset_id"):
            try:
                asset = Asset.objects.get(pk=data["asset_id"])
            except Asset.DoesNotExist:
                return Response(
                    {"detail": "Asset not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if not location_in_scope(asset.current_location_id, request.user):
                return Response(
                    {"detail": "Asset is outside your allowed scope."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        try:
            submission = create_submission(
                submitted_by=request.user,
                submission_type=data["submission_type"],
                location=location,
                submitted_at=timezone.now(),
                asset=asset,
                asset_name=data.get("asset_name"),
                serial_number=data.get("serial_number"),
                asset_type_name=data.get("asset_type_name"),
                remarks=data.get("remarks"),
            )
        except Exception as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        _save_uploaded_photos(submission, request)

        result = FieldSubmissionSerializer(
            submission, context={"request": request}
        ).data
        return Response(result, status=status.HTTP_201_CREATED)


class SubmissionDetailView(APIView):
    """GET /api/submissions/{id}/ — single submission detail.

    Access: the original submitter, or a user with ``submission.review``
    whose location scope covers the submission's location.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            submission = (
                FieldSubmission.objects.select_related(
                    "asset", "location", "submitted_by"
                )
                .prefetch_related("photos", "reviews__reviewed_by")
                .get(pk=pk)
            )
        except FieldSubmission.DoesNotExist:
            return Response(
                {"detail": "Submission not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_submitter = submission.submitted_by_id == request.user.pk
        has_review = "submission.review" in get_user_permission_codes(request.user)

        if is_submitter:
            pass
        elif has_review and location_in_scope(submission.location_id, request.user):
            pass
        else:
            return Response(
                {"detail": "Submission not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = FieldSubmissionSerializer(
            submission, context={"request": request}
        )
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Admin review endpoints
# ---------------------------------------------------------------------------


class AdminSubmissionListView(APIView):
    """GET — list all submissions (admin review queue), location-scoped."""

    permission_classes = [IsAuthenticated, permission_required("submission.review")]

    def get(self, request):
        qs = (
            FieldSubmission.objects.select_related(
                "asset", "location", "submitted_by"
            )
            .prefetch_related("photos", "reviews__reviewed_by")
            .order_by("-submitted_at")
        )

        qs = filter_by_location_scope(qs, request.user, location_field="location")

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        sub_type = request.query_params.get("type")
        if sub_type:
            qs = qs.filter(submission_type=sub_type)

        from rest_framework.pagination import PageNumberPagination

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 25))
        page = paginator.paginate_queryset(qs, request)
        serializer = FieldSubmissionSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)


class AdminSubmissionDetailView(APIView):
    """GET /api/admin/submissions/{id}/ — single submission detail (admin, location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("submission.review")]

    def get(self, request, pk):
        submission = _get_scoped_submission(pk, request.user)
        if submission is None:
            return Response({"detail": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = FieldSubmissionSerializer(submission, context={"request": request})
        return Response(serializer.data)


class AdminSubmissionReviewView(APIView):
    """POST /api/submissions/{id}/review/ — approve / reject / request correction (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("submission.review")]

    def post(self, request, pk):
        submission = _get_scoped_submission(pk, request.user)
        if submission is None:
            return Response({"detail": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AdminReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]
        notes = serializer.validated_data.get("review_notes", "")

        try:
            if decision == "approved":
                approve_submission(submission, request.user, notes=notes)
            elif decision == "rejected":
                reject_submission(submission, request.user, notes=notes)
            elif decision == "correction_requested":
                request_submission_correction(submission, request.user, notes=notes)
            else:
                return Response(
                    {"detail": f"Unknown decision: {decision}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        submission.refresh_from_db()
        return Response(FieldSubmissionSerializer(submission, context={"request": request}).data)


class AdminSubmissionApproveView(APIView):
    """POST /api/admin/submissions/{id}/approve — shortcut approve (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("submission.review")]

    def post(self, request, pk):
        submission = _get_scoped_submission(pk, request.user)
        if submission is None:
            return Response({"detail": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        notes = request.data.get("review_notes", "")
        try:
            approve_submission(submission, request.user, notes=notes)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        submission.refresh_from_db()
        return Response(FieldSubmissionSerializer(submission, context={"request": request}).data)


class AdminSubmissionRejectView(APIView):
    """POST /api/admin/submissions/{id}/reject — shortcut reject (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("submission.review")]

    def post(self, request, pk):
        submission = _get_scoped_submission(pk, request.user)
        if submission is None:
            return Response({"detail": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        notes = request.data.get("review_notes", "")
        try:
            reject_submission(submission, request.user, notes=notes)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        submission.refresh_from_db()
        return Response(FieldSubmissionSerializer(submission, context={"request": request}).data)


class AdminSubmissionCorrectionView(APIView):
    """POST /api/admin/submissions/{id}/correction — request correction (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("submission.review")]

    def post(self, request, pk):
        submission = _get_scoped_submission(pk, request.user)
        if submission is None:
            return Response({"detail": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        notes = request.data.get("review_notes", "")
        try:
            request_submission_correction(submission, request.user, notes=notes)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        submission.refresh_from_db()
        return Response(FieldSubmissionSerializer(submission, context={"request": request}).data)


class AdminSubmissionConvertView(APIView):
    """POST /api/admin/submissions/{id}/convert-to-asset — convert approved candidate (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("submission.review"), permission_required("asset.create")]

    def post(self, request, pk):
        submission = _get_scoped_submission(pk, request.user)
        if submission is None:
            return Response({"detail": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = ConvertToAssetSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        if not location_in_scope(d["location_id"], request.user):
            return Response(
                {"detail": "Target location is outside your allowed scope."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            asset = convert_candidate_to_asset(
                submission,
                asset_id=d["asset_id"],
                name=d["name"],
                category_id=d["category_id"],
                location_id=d["location_id"],
                serial_number=d.get("serial_number"),
                description=d.get("description"),
                created_by=request.user,
            )
        except (ValueError, Exception) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        from assets.serializers import AssetDetailSerializer

        return Response(
            AssetDetailSerializer(asset, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Compatibility endpoints — real work, no stubs
# ---------------------------------------------------------------------------


class ThirdPartyVerifyView(APIView):
    """POST /api/third-party/verify — create a verification_existing submission."""

    permission_classes = [IsAuthenticated, permission_required("submission.create")]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        asset_id = request.data.get("asset_id")
        location_id = request.data.get("location_id")
        remarks = request.data.get("remarks", "")

        if not asset_id or not location_id:
            return Response(
                {"detail": "asset_id and location_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        loc_uuid = _parse_uuid(location_id, "location_id")
        if loc_uuid is None:
            return _BAD_UUID("location_id")

        asset_uuid = _parse_uuid(asset_id, "asset_id")
        if asset_uuid is not None:
            try:
                asset = Asset.objects.get(pk=asset_uuid)
            except Asset.DoesNotExist:
                asset = None
        else:
            asset = None

        if asset is None:
            try:
                asset = Asset.objects.get(asset_id=str(asset_id))
            except Asset.DoesNotExist:
                return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            location = LocationNode.objects.get(pk=loc_uuid)
        except LocationNode.DoesNotExist:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)

        if not location_in_scope(location.pk, request.user):
            return Response({"detail": "Location is outside your allowed scope."}, status=status.HTTP_403_FORBIDDEN)

        if not location_in_scope(asset.current_location_id, request.user):
            return Response({"detail": "Asset is outside your allowed scope."}, status=status.HTTP_403_FORBIDDEN)

        try:
            submission = create_submission(
                submitted_by=request.user,
                submission_type=FieldSubmission.SubmissionType.VERIFICATION_EXISTING,
                location=location,
                submitted_at=timezone.now(),
                asset=asset,
                remarks=remarks,
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        _save_uploaded_photos(submission, request)
        return Response(
            FieldSubmissionSerializer(submission, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class ThirdPartyAddAssetView(APIView):
    """POST /api/third-party/add-asset — create a new_asset_candidate submission."""

    permission_classes = [IsAuthenticated, permission_required("submission.create")]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        location_id = request.data.get("location_id")
        asset_name = request.data.get("asset_name", "")
        serial_number = request.data.get("serial_number", "")
        asset_type_name = request.data.get("asset_type_name", "")
        remarks = request.data.get("remarks", "")

        if not location_id or not asset_name:
            return Response(
                {"detail": "location_id and asset_name are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        loc_uuid = _parse_uuid(location_id, "location_id")
        if loc_uuid is None:
            return _BAD_UUID("location_id")

        try:
            location = LocationNode.objects.get(pk=loc_uuid)
        except LocationNode.DoesNotExist:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)

        if not location_in_scope(location.pk, request.user):
            return Response({"detail": "Location is outside your allowed scope."}, status=status.HTTP_403_FORBIDDEN)

        try:
            submission = create_submission(
                submitted_by=request.user,
                submission_type=FieldSubmission.SubmissionType.NEW_ASSET_CANDIDATE,
                location=location,
                submitted_at=timezone.now(),
                asset_name=asset_name,
                serial_number=serial_number,
                asset_type_name=asset_type_name,
                remarks=remarks,
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        _save_uploaded_photos(submission, request)
        return Response(
            FieldSubmissionSerializer(submission, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class AdminApproveAssetView(APIView):
    """POST /api/admin/approve-asset — approve a submission by submission_id (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("submission.review")]

    def post(self, request):
        submission_id = request.data.get("submission_id")
        if not submission_id:
            return Response({"detail": "submission_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        sub_uuid = _parse_uuid(submission_id, "submission_id")
        if sub_uuid is None:
            return _BAD_UUID("submission_id")

        submission = _get_scoped_submission(sub_uuid, request.user)
        if submission is None:
            return Response({"detail": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        notes = request.data.get("review_notes", "")
        try:
            approve_submission(submission, request.user, notes=notes)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        submission.refresh_from_db()
        return Response(FieldSubmissionSerializer(submission, context={"request": request}).data)


class AdminRejectAssetView(APIView):
    """POST /api/admin/reject-asset — reject a submission by submission_id (location-scoped)."""

    permission_classes = [IsAuthenticated, permission_required("submission.review")]

    def post(self, request):
        submission_id = request.data.get("submission_id")
        if not submission_id:
            return Response({"detail": "submission_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        sub_uuid = _parse_uuid(submission_id, "submission_id")
        if sub_uuid is None:
            return _BAD_UUID("submission_id")

        submission = _get_scoped_submission(sub_uuid, request.user)
        if submission is None:
            return Response({"detail": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        notes = request.data.get("review_notes", "")
        try:
            reject_submission(submission, request.user, notes=notes)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        submission.refresh_from_db()
        return Response(FieldSubmissionSerializer(submission, context={"request": request}).data)


class ReconciliationSubmitView(APIView):
    """POST /api/reconciliation/submit — create a field submission (either type).

    Accepts ``asset_id`` (for verification_existing) or ``asset_name``
    (for new_asset_candidate) and creates the appropriate submission type.
    """

    permission_classes = [IsAuthenticated, permission_required("submission.create")]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        location_id = request.data.get("location_id")
        if not location_id:
            return Response({"detail": "location_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        loc_uuid = _parse_uuid(location_id, "location_id")
        if loc_uuid is None:
            return _BAD_UUID("location_id")

        try:
            location = LocationNode.objects.get(pk=loc_uuid)
        except LocationNode.DoesNotExist:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)

        if not location_in_scope(location.pk, request.user):
            return Response({"detail": "Location is outside your allowed scope."}, status=status.HTTP_403_FORBIDDEN)

        asset_id = request.data.get("asset_id")
        asset_name = request.data.get("asset_name", "")
        remarks = request.data.get("remarks", "")

        if asset_id:
            asset_uuid = _parse_uuid(asset_id, "asset_id")
            asset = None
            if asset_uuid is not None:
                try:
                    asset = Asset.objects.get(pk=asset_uuid)
                except Asset.DoesNotExist:
                    pass
            if asset is None:
                try:
                    asset = Asset.objects.get(asset_id=str(asset_id))
                except Asset.DoesNotExist:
                    return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)
            if not location_in_scope(asset.current_location_id, request.user):
                return Response({"detail": "Asset is outside your allowed scope."}, status=status.HTTP_403_FORBIDDEN)
            sub_type = FieldSubmission.SubmissionType.VERIFICATION_EXISTING
            kwargs = {"asset": asset}
        elif asset_name:
            sub_type = FieldSubmission.SubmissionType.NEW_ASSET_CANDIDATE
            kwargs = {
                "asset_name": asset_name,
                "serial_number": request.data.get("serial_number", ""),
                "asset_type_name": request.data.get("asset_type_name", ""),
            }
        else:
            return Response(
                {"detail": "Provide asset_id (existing) or asset_name (new candidate)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            submission = create_submission(
                submitted_by=request.user,
                submission_type=sub_type,
                location=location,
                submitted_at=timezone.now(),
                remarks=remarks,
                **kwargs,
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        _save_uploaded_photos(submission, request)
        return Response(
            FieldSubmissionSerializer(submission, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Employee verification compatibility endpoints
# ---------------------------------------------------------------------------


class EmployeeVerifyAssetsView(APIView):
    """POST /api/employee/verify-assets — submit asset responses via public_token.

    Delegates to the existing public verification submit flow.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        from verification.views import PublicSubmitView

        public_token = request.data.get("public_token")
        if not public_token:
            return Response({"detail": "public_token is required."}, status=status.HTTP_400_BAD_REQUEST)

        view = PublicSubmitView.as_view()
        return view(request._request, token=public_token)


class EmployeeSubmitVerificationView(APIView):
    """POST /api/employee/submit-verification — alias for verify-assets."""

    permission_classes = [AllowAny]

    def post(self, request):
        from verification.views import PublicSubmitView

        public_token = request.data.get("public_token")
        if not public_token:
            return Response({"detail": "public_token is required."}, status=status.HTTP_400_BAD_REQUEST)

        view = PublicSubmitView.as_view()
        return view(request._request, token=public_token)


class EmployeeAddMissingAssetView(APIView):
    """POST /api/employee/add-missing-asset — submit a new_asset_candidate
    from the employee verification flow.

    Creates a FieldSubmission(submission_type=new_asset_candidate).
    Requires either JWT auth or a valid ``public_token`` that resolves to an
    employee user.

    Scope rules:
    - public_token path: location must be inside the VR's location_scope subtree
      (or unrestricted if the VR has no location_scope — global request).
    - authenticated path: location must pass the user's normal location scope.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        from verification.models import VerificationRequest

        public_token = request.data.get("public_token")
        location_id = request.data.get("location_id")
        asset_name = request.data.get("asset_name", "")

        if not location_id or not asset_name:
            return Response(
                {"detail": "location_id and asset_name are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        loc_uuid = _parse_uuid(location_id, "location_id")
        if loc_uuid is None:
            return _BAD_UUID("location_id")

        vr = None
        if public_token:
            try:
                vr = VerificationRequest.objects.select_related("employee").get(
                    public_token=public_token
                )
            except VerificationRequest.DoesNotExist:
                return Response({"detail": "Invalid public_token."}, status=status.HTTP_404_NOT_FOUND)

            if vr.status != VerificationRequest.Status.OTP_VERIFIED:
                return Response(
                    {"detail": f"Verification request must be OTP-verified first. Current status: {vr.status}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            submitter = vr.employee
        elif request.user and request.user.is_authenticated:
            submitter = request.user
        else:
            return Response(
                {"detail": "Authentication or public_token required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            location = LocationNode.objects.get(pk=loc_uuid)
        except LocationNode.DoesNotExist:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)

        if vr is not None:
            if vr.location_scope_id is not None:
                in_subtree = LocationClosure.objects.filter(
                    ancestor_id=vr.location_scope_id,
                    descendant_id=location.pk,
                ).exists()
                if not in_subtree:
                    return Response(
                        {"detail": "Location is outside the verification request scope."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
        else:
            if not location_in_scope(location.pk, request.user):
                return Response(
                    {"detail": "Location is outside your allowed scope."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        try:
            submission = create_submission(
                submitted_by=submitter,
                submission_type=FieldSubmission.SubmissionType.NEW_ASSET_CANDIDATE,
                location=location,
                submitted_at=timezone.now(),
                asset_name=asset_name,
                serial_number=request.data.get("serial_number", ""),
                asset_type_name=request.data.get("asset_type_name", ""),
                remarks=request.data.get("remarks", ""),
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            FieldSubmissionSerializer(submission, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )
