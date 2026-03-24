from rest_framework import serializers

from verification.models import (
    AssetVerificationResponse,
    VerificationAssetPhoto,
    VerificationCycle,
    VerificationDeclaration,
    VerificationIssue,
    VerificationRequest,
    VerificationRequestAsset,
)


# ---------------------------------------------------------------------------
# Actionability helpers (used by public serializer)
# ---------------------------------------------------------------------------

def _compute_actionable_vra_ids(vr) -> set:
    """
    For a correction_requested VerificationRequest, return the set of
    VerificationRequestAsset PKs that still require employee action.

    A VRA is actionable when:
      1. Its admin_review_status is correction_required, AND
      2. The same underlying asset has NOT been included in a newer
         (post-dating this VR) employee verification request that is
         active or already approved.

    Uses 2 DB queries regardless of how many assets are in the request.
    """
    # Step 1: collect correction_required VRA rows for this request
    cr_rows = list(
        AssetVerificationResponse.objects
        .filter(
            request_asset__verification_request=vr,
            admin_review_status=AssetVerificationResponse.AdminReviewStatus.CORRECTION_REQUIRED,
        )
        .values("request_asset_id", "request_asset__asset_id")
    )
    if not cr_rows:
        return set()

    vra_to_asset = {r["request_asset_id"]: r["request_asset__asset_id"] for r in cr_rows}
    cr_asset_ids = list(vra_to_asset.values())

    # Step 2: which of those assets have been picked up by a newer request?
    _post_statuses = [
        VerificationRequest.Status.PENDING,
        VerificationRequest.Status.OPENED,
        VerificationRequest.Status.OTP_VERIFIED,
        VerificationRequest.Status.SUBMITTED,
        VerificationRequest.Status.CORRECTION_REQUESTED,
        VerificationRequest.Status.APPROVED,
    ]
    superseded_asset_ids = set(
        VerificationRequestAsset.objects
        .filter(
            asset_id__in=cr_asset_ids,
            verification_request__created_at__gt=vr.created_at,
            verification_request__status__in=_post_statuses,
        )
        .exclude(verification_request=vr)
        .values_list("asset_id", flat=True)
    )

    # Step 3: VRA PKs for assets that are still non-superseded
    return {
        vra_id
        for vra_id, asset_id in vra_to_asset.items()
        if asset_id not in superseded_asset_ids
    }


class VerificationDeclarationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationDeclaration
        fields = [
            "id",
            "declared_by_name",
            "declared_by_email",
            "consented_at",
            "consent_text_version",
        ]


class VerificationCycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationCycle
        fields = [
            "id",
            "name",
            "code",
            "description",
            "start_date",
            "end_date",
            "status",
            "created_at",
        ]


class VerificationAssetPhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = VerificationAssetPhoto
        fields = ["id", "url", "uploaded_at"]

    def get_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url


class VerificationRequestAssetSerializer(serializers.ModelSerializer):
    assetId = serializers.CharField(source="snapshot_asset_id")
    name = serializers.CharField(source="snapshot_name")
    serialNumber = serializers.CharField(source="snapshot_serial_number")
    categoryName = serializers.CharField(source="snapshot_category_name")
    locationName = serializers.CharField(source="snapshot_location_name")
    response = serializers.SerializerMethodField()
    photos = VerificationAssetPhotoSerializer(many=True, read_only=True)
    is_actionable = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequestAsset
        fields = [
            "id",
            "assetId",
            "name",
            "serialNumber",
            "categoryName",
            "locationName",
            "sort_order",
            "photos",
            "response",
            "is_actionable",
        ]

    def get_response(self, obj):
        try:
            resp = obj.response
            data = {
                "response": resp.response,
                "remarks": resp.remarks,
                "responded_at": resp.responded_at.isoformat() if resp.responded_at else None,
                "admin_review_status": resp.admin_review_status,
                "admin_review_note": resp.admin_review_note,
            }
            try:
                issue = resp.issue
                data["issue"] = {
                    "issue_type": issue.issue_type,
                    "description": issue.description,
                }
            except VerificationIssue.DoesNotExist:
                data["issue"] = None
            return data
        except AssetVerificationResponse.DoesNotExist:
            return None

    def get_is_actionable(self, obj):
        """
        None  — not in a correction context (initial/non-correction request).
        True  — this asset still needs employee action (correction_required, not superseded).
        False — this asset is locked (approved, missing, or superseded by a newer request).

        Populated by PublicVerificationRequestSerializer which injects
        'actionable_vra_ids' into serializer context for correction_requested requests.
        """
        actionable_ids = self.context.get("actionable_vra_ids")
        if actionable_ids is None:
            return None  # Not in correction context
        return obj.pk in actionable_ids


class VerificationRequestSerializer(serializers.ModelSerializer):
    """List serializer — also used as admin review inbox items."""

    source_type = serializers.SerializerMethodField()
    cycleName = serializers.CharField(source="cycle.name", read_only=True)
    cycleCode = serializers.CharField(source="cycle.code", read_only=True)
    employeeId = serializers.UUIDField(source="employee.id", read_only=True)
    employeeEmail = serializers.EmailField(source="employee.email", read_only=True)
    employeeName = serializers.SerializerMethodField()
    locationScopeId = serializers.SerializerMethodField()
    locationScopeName = serializers.SerializerMethodField()
    assetCount = serializers.SerializerMethodField()
    verifiedCount = serializers.SerializerMethodField()
    issueCount = serializers.SerializerMethodField()
    reportCount = serializers.SerializerMethodField()
    declarationPresent = serializers.SerializerMethodField()
    approvedCount = serializers.SerializerMethodField()
    correctionCount = serializers.SerializerMethodField()
    missingCount = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = [
            "id",
            "source_type",
            "reference_code",
            "cycleName",
            "cycleCode",
            "employeeId",
            "employeeEmail",
            "employeeName",
            "locationScopeId",
            "locationScopeName",
            "status",
            "request_type",
            "review_notes",
            "sent_at",
            "opened_at",
            "otp_verified_at",
            "submitted_at",
            "expires_at",
            "created_at",
            "assetCount",
            "verifiedCount",
            "issueCount",
            "reportCount",
            "declarationPresent",
            "approvedCount",
            "correctionCount",
            "missingCount",
        ]

    def get_source_type(self, obj):
        return "employee_verification"

    def get_employeeName(self, obj):
        return obj.employee.get_full_name()

    def get_locationScopeId(self, obj):
        return str(obj.location_scope_id) if obj.location_scope_id else None

    def get_locationScopeName(self, obj):
        return obj.location_scope.name if obj.location_scope_id else None

    def get_assetCount(self, obj):
        return obj.request_assets.count()

    def get_verifiedCount(self, obj):
        return AssetVerificationResponse.objects.filter(
            request_asset__verification_request=obj,
            response=AssetVerificationResponse.Response.VERIFIED,
        ).count()

    def get_issueCount(self, obj):
        return AssetVerificationResponse.objects.filter(
            request_asset__verification_request=obj,
            response=AssetVerificationResponse.Response.ISSUE_REPORTED,
        ).count()

    def get_reportCount(self, obj):
        return obj.employee_reports.count()

    def get_declarationPresent(self, obj):
        try:
            return obj.declaration is not None
        except VerificationDeclaration.DoesNotExist:
            return False

    def get_approvedCount(self, obj):
        return AssetVerificationResponse.objects.filter(
            request_asset__verification_request=obj,
            admin_review_status=AssetVerificationResponse.AdminReviewStatus.APPROVED,
        ).count()

    def get_correctionCount(self, obj):
        return AssetVerificationResponse.objects.filter(
            request_asset__verification_request=obj,
            admin_review_status=AssetVerificationResponse.AdminReviewStatus.CORRECTION_REQUIRED,
        ).count()

    def get_missingCount(self, obj):
        return AssetVerificationResponse.objects.filter(
            request_asset__verification_request=obj,
            admin_review_status=AssetVerificationResponse.AdminReviewStatus.MISSING,
        ).count()


class VerificationRequestDetailSerializer(VerificationRequestSerializer):
    """Full detail with request_assets, employee_reports and declaration."""

    request_assets = VerificationRequestAssetSerializer(many=True, read_only=True)
    declaration = VerificationDeclarationSerializer(read_only=True)
    verification_link = serializers.SerializerMethodField()

    class Meta(VerificationRequestSerializer.Meta):
        fields = VerificationRequestSerializer.Meta.fields + ["request_assets", "employee_reports", "declaration", "verification_link"]

    def get_verification_link(self, obj):
        from django.conf import settings
        frontend_base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:8080")
        return f"{frontend_base}/verify/{obj.public_token}"

    def to_representation(self, instance):
        from verification.serializers import EmployeeAssetReportSerializer
        ret = super().to_representation(instance)
        ret["employee_reports"] = EmployeeAssetReportSerializer(
            instance.employee_reports.all(), many=True, context=self.context
        ).data
        return ret


class AssetVerificationResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetVerificationResponse
        fields = ["id", "response", "remarks", "responded_at"]


class VerificationIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationIssue
        fields = ["id", "issue_type", "description"]


# ---- Create serializers ----


class CreateVerificationRequestSerializer(serializers.Serializer):
    cycle_id = serializers.UUIDField()
    employee_id = serializers.UUIDField()
    asset_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, help_text="Explicit list of asset UUIDs to include."
    )
    location_scope_id = serializers.UUIDField(required=False, allow_null=True)
    reference_code = serializers.CharField(max_length=100, required=False)
    request_type = serializers.ChoiceField(
        choices=VerificationRequest.RequestType.choices,
        required=False,
        default=VerificationRequest.RequestType.INITIAL,
    )


# ---- Public portal serializers ----


class PublicVerificationRequestSerializer(serializers.ModelSerializer):
    """Safe public version of the request."""

    employeeName = serializers.SerializerMethodField()
    employeeEmail = serializers.EmailField(source="employee.email")
    cycleName = serializers.CharField(source="cycle.name")
    assets = serializers.SerializerMethodField()
    employee_reports = serializers.SerializerMethodField()
    review_notes = serializers.CharField(default="")
    correction_summary = serializers.SerializerMethodField()
    employee_action_required = serializers.SerializerMethodField()
    is_superseded = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = [
            "id",
            "reference_code",
            "status",
            "request_type",
            "employeeName",
            "employeeEmail",
            "cycleName",
            "assets",
            "employee_reports",
            "review_notes",
            "correction_summary",
            "employee_action_required",
            "is_superseded",
        ]

    # ------------------------------------------------------------------
    # Actionability cache (avoid re-computing within the same serialization)
    # ------------------------------------------------------------------

    def _get_actionable_vra_ids(self, obj):
        if not hasattr(self, "_actionable_vra_ids_cache"):
            if obj.status == VerificationRequest.Status.CORRECTION_REQUESTED:
                self._actionable_vra_ids_cache = _compute_actionable_vra_ids(obj)
            else:
                self._actionable_vra_ids_cache = None  # Not a correction context
        return self._actionable_vra_ids_cache

    # ------------------------------------------------------------------
    # New derived fields
    # ------------------------------------------------------------------

    def get_employee_action_required(self, obj):
        """
        True when the employee still needs to take action on this request.

        For correction_requested: True iff at least one asset is still
        correction_required AND has not been superseded by a newer request.
        For other actionable statuses: always True.
        For terminal statuses: False.
        """
        _actionable_statuses = {
            VerificationRequest.Status.PENDING,
            VerificationRequest.Status.OPENED,
            VerificationRequest.Status.OTP_VERIFIED,
            VerificationRequest.Status.CORRECTION_REQUESTED,
        }
        if obj.status not in _actionable_statuses:
            return False
        if obj.status != VerificationRequest.Status.CORRECTION_REQUESTED:
            return True
        return bool(self._get_actionable_vra_ids(obj))

    def get_is_superseded(self, obj):
        """
        True when this correction_requested request has no more actionable
        assets — either all were resolved by the admin review (approved /
        missing) or they have been included in a newer employee request.

        Always False for non-correction_requested requests.
        """
        if obj.status != VerificationRequest.Status.CORRECTION_REQUESTED:
            return False
        return not bool(self._get_actionable_vra_ids(obj))

    def get_employeeName(self, obj):
        return obj.employee.get_full_name()

    def get_assets(self, obj):
        qs = obj.request_assets.all().order_by("sort_order")
        # Inject actionable_vra_ids so the nested serializer can set is_actionable
        actionable_ids = self._get_actionable_vra_ids(obj)
        ctx = {**self.context, "actionable_vra_ids": actionable_ids}
        return VerificationRequestAssetSerializer(qs, many=True, context=ctx).data

    def get_employee_reports(self, obj):
        from verification.serializers import EmployeeAssetReportSerializer
        return EmployeeAssetReportSerializer(
            obj.employee_reports.all(), many=True, context=self.context
        ).data

    def get_correction_summary(self, obj):
        if obj.status != VerificationRequest.Status.CORRECTION_REQUESTED:
            return None
        responses = AssetVerificationResponse.objects.filter(
            request_asset__verification_request=obj
        )
        return {
            "total": responses.count(),
            "approved": responses.filter(
                admin_review_status=AssetVerificationResponse.AdminReviewStatus.APPROVED
            ).count(),
            "correction_required": responses.filter(
                admin_review_status=AssetVerificationResponse.AdminReviewStatus.CORRECTION_REQUIRED
            ).count(),
            "missing": responses.filter(
                admin_review_status=AssetVerificationResponse.AdminReviewStatus.MISSING
            ).count(),
        }


class PublicAssetResponseSerializer(serializers.Serializer):
    """For submit payload."""

    request_asset_id = serializers.UUIDField()
    response = serializers.ChoiceField(
        choices=AssetVerificationResponse.Response.choices
    )
    remarks = serializers.CharField(required=False, allow_blank=True, default="")
    issue_type = serializers.ChoiceField(
        choices=VerificationIssue.IssueType.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    issue_description = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class PublicSubmitSerializer(serializers.Serializer):
    """Full submit payload."""

    responses = PublicAssetResponseSerializer(many=True)
    declared_by_name = serializers.CharField(max_length=200)
    declared_by_email = serializers.EmailField()
    consent_text_version = serializers.CharField(
        max_length=50, required=False, default="1.0"
    )


# ---- Employee asset report serializers ----

from verification.models import EmployeeAssetReport, EmployeeReportPhoto


class EmployeeReportPhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeReportPhoto
        fields = ["id", "url", "uploaded_at"]

    def get_url(self, obj):
        request = self.context.get("request")
        if request and obj.image:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url if obj.image else None


class EmployeeAssetReportSerializer(serializers.ModelSerializer):
    photos = EmployeeReportPhotoSerializer(many=True, read_only=True)

    class Meta:
        model = EmployeeAssetReport
        fields = [
            "id",
            "report_type",
            "asset_name",
            "asset_id_if_known",
            "serial_number",
            "category_name",
            "location_description",
            "expected_location",
            "remarks",
            "status",
            "photos",
            "created_at",
        ]


class CreateEmployeeAssetReportSerializer(serializers.Serializer):
    report_type = serializers.ChoiceField(choices=EmployeeAssetReport.ReportType.choices)
    asset_name = serializers.CharField(max_length=300)
    asset_id_if_known = serializers.CharField(max_length=100, required=False, allow_blank=True)
    serial_number = serializers.CharField(max_length=200, required=False, allow_blank=True)
    category_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    location_description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    expected_location = serializers.CharField(max_length=500, required=False, allow_blank=True)
    remarks = serializers.CharField(required=False, allow_blank=True)


# ---- Admin verification review serializers ----


class AssetReviewItemSerializer(serializers.Serializer):
    request_asset_id = serializers.UUIDField()
    decision = serializers.ChoiceField(choices=["approved", "correction_required", "missing"])
    note = serializers.CharField(required=False, allow_blank=True, default="")


class AdminReviewActionSerializer(serializers.Serializer):
    review_note = serializers.CharField(required=False, allow_blank=True, default="")
    asset_reviews = AssetReviewItemSerializer(many=True, min_length=1)
