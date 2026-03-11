import secrets
import uuid

from django.core.exceptions import ValidationError
from django.db import models


def _generate_public_token():
    """Generate a 43-character URL-safe random token for emailed verification links."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Verification Cycle
# ---------------------------------------------------------------------------

class VerificationCycle(models.Model):
    """An audit / reconciliation cycle, e.g. 'FY 2025-26 Q1 Verification'.

    Acts as the parent container for all VerificationRequests in a given period.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_verification_cycles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "verification_cycle"
        ordering = ("-start_date",)

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("end_date must be on or after start_date.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


# ---------------------------------------------------------------------------
# Verification Request
# ---------------------------------------------------------------------------

class VerificationRequest(models.Model):
    """A verification request sent to one employee within one cycle.

    OTP linkage (no extra model needed):
        accounts.OtpChallenge with
            purpose             = OtpChallenge.Purpose.EMPLOYEE_VERIFICATION
            related_object_type = "VerificationRequest"
            related_object_id   = str(self.pk)

    Email linkage (no extra model needed):
        accounts.OutboundEmail with
            related_object_type = "VerificationRequest"
            related_object_id   = str(self.pk)
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        OPENED = "opened", "Opened"
        OTP_VERIFIED = "otp_verified", "OTP Verified"
        SUBMITTED = "submitted", "Submitted"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    cycle = models.ForeignKey(
        VerificationCycle,
        on_delete=models.PROTECT,
        related_name="requests",
    )
    employee = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="verification_requests",
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_verification_requests",
    )
    # Optional: narrow the scope of assets to a specific location subtree
    location_scope = models.ForeignKey(
        "locations.LocationNode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verification_requests",
    )

    # Emailed to employee as part of the magic-link URL — never guessable
    public_token = models.CharField(
        max_length=200, unique=True, db_index=True, default=_generate_public_token
    )
    # Human-readable reference shown in emails and the admin UI (e.g. VER-2526-00042)
    reference_code = models.CharField(max_length=100, unique=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    # Audit timestamps — set by the service layer, not auto_now
    sent_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    otp_verified_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Statuses where the employee is still expected to act — only one of these
    # may exist per employee per cycle at any time. Terminal statuses (submitted,
    # expired, cancelled) are historical and do not block a new request.
    ACTIVE_STATUSES = {Status.PENDING, Status.OPENED, Status.OTP_VERIFIED}

    class Meta:
        db_table = "verification_request"
        # No DB-level unique_together — multiple historical requests per employee per cycle
        # are valid (expired → resent, cancelled → reissued, etc.). Active-state uniqueness
        # is enforced in clean() so audit history is never discarded.
        indexes = [
            models.Index(fields=["cycle", "employee"], name="verif_req_cycle_emp_idx"),  # fast lookup without uniqueness
            models.Index(fields=["employee"], name="verif_req_employee_idx"),
            models.Index(fields=["status"], name="verif_req_status_idx"),
            models.Index(fields=["expires_at"], name="verif_req_expires_at_idx"),
        ]

    def clean(self):
        # Block creating/activating a second open request for the same employee+cycle.
        # Terminal requests (submitted / expired / cancelled) are allowed to co-exist.
        if self.status in self.ACTIVE_STATUSES and self.cycle_id and self.employee_id:
            qs = VerificationRequest.objects.filter(
                cycle_id=self.cycle_id,
                employee_id=self.employee_id,
                status__in=self.ACTIVE_STATUSES,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    "This employee already has an active verification request in this cycle. "
                    "Cancel or expire it before issuing a new one."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference_code} — {self.employee.email} ({self.cycle.code})"


# ---------------------------------------------------------------------------
# Verification Request Asset (snapshot)
# ---------------------------------------------------------------------------

class VerificationRequestAsset(models.Model):
    """Snapshot of each asset included in a verification request.

    Snapshot fields are captured at send-time so that subsequent changes to the
    live asset record do not alter what the employee was asked to verify.
    The live FK is kept for admin drill-through; the snapshot_* fields are the
    authoritative data for the verification flow.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification_request = models.ForeignKey(
        VerificationRequest,
        # Cascade: asset list is meaningless without its parent request
        on_delete=models.CASCADE,
        related_name="request_assets",
    )
    asset = models.ForeignKey(
        "assets.Asset",
        # PROTECT: don't silently discard a verification snapshot if an asset is deleted
        on_delete=models.PROTECT,
        related_name="verification_snapshots",
    )

    # --- Snapshot fields (stable copy captured at send-time) ---
    snapshot_asset_id = models.CharField(max_length=100)
    snapshot_name = models.CharField(max_length=300)
    snapshot_serial_number = models.CharField(max_length=200, blank=True, null=True)
    snapshot_category_name = models.CharField(max_length=200, blank=True, null=True)
    snapshot_location_name = models.CharField(max_length=300, blank=True, null=True)
    # Full raw payload for anything else audit/frontend might need later
    snapshot_payload = models.JSONField(default=dict, blank=True)

    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "verification_request_asset"
        unique_together = (("verification_request", "asset"),)
        ordering = ("sort_order",)
        indexes = [
            models.Index(fields=["verification_request"], name="verif_rqa_request_idx"),
            models.Index(fields=["asset"], name="verif_rqa_asset_idx"),
        ]

    def __str__(self):
        return f"{self.snapshot_asset_id} in {self.verification_request.reference_code}"


# ---------------------------------------------------------------------------
# Asset Verification Response
# ---------------------------------------------------------------------------

class AssetVerificationResponse(models.Model):
    """Employee's response for one asset within a verification request.

    OneToOne with VerificationRequestAsset ensures exactly one response per asset.
    """

    class Response(models.TextChoices):
        VERIFIED = "verified", "Verified"
        ISSUE_REPORTED = "issue_reported", "Issue Reported"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_asset = models.OneToOneField(
        VerificationRequestAsset,
        on_delete=models.CASCADE,
        related_name="response",
    )
    response = models.CharField(max_length=20, choices=Response.choices, db_index=True)
    remarks = models.TextField(blank=True, null=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "verification_asset_response"

    def __str__(self):
        return f"{self.response} — {self.request_asset}"


# ---------------------------------------------------------------------------
# Verification Issue
# ---------------------------------------------------------------------------

class VerificationIssue(models.Model):
    """Issue detail reported by an employee for a specific asset.

    Only valid when the linked AssetVerificationResponse has response='issue_reported'.
    OneToOne with AssetVerificationResponse so at most one issue record exists per response.
    """

    class IssueType(models.TextChoices):
        MISSING = "missing", "Missing"
        DAMAGED = "damaged", "Damaged"
        WRONG_SERIAL = "wrong_serial", "Wrong Serial Number"
        NOT_IN_POSSESSION = "not_in_possession", "Not In Possession"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset_response = models.OneToOneField(
        AssetVerificationResponse,
        on_delete=models.CASCADE,
        related_name="issue",
    )
    issue_type = models.CharField(max_length=30, choices=IssueType.choices)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "verification_issue"

    def clean(self):
        # An issue record is only meaningful when the employee actually reported an issue
        if (
            self.asset_response_id
            and self.asset_response.response
            != AssetVerificationResponse.Response.ISSUE_REPORTED
        ):
            raise ValidationError(
                "A VerificationIssue can only be attached to a response with "
                "status 'issue_reported'."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.issue_type} — {self.asset_response}"


# ---------------------------------------------------------------------------
# Verification Declaration
# ---------------------------------------------------------------------------

class VerificationDeclaration(models.Model):
    """Final declaration / consent submitted by the employee at the end of the flow.

    This is the legally and audit-relevant acknowledgment. It is intentionally
    de-coupled from the User session — declared_by_name / declared_by_email are
    captured verbatim at submission time so the record remains self-contained
    even if the user account is later deactivated or renamed.

    PROTECT is used so the declaration survives even if other parts of the workflow
    are administratively cleaned up.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification_request = models.OneToOneField(
        VerificationRequest,
        # PROTECT: a signed declaration must never be silently lost
        on_delete=models.PROTECT,
        related_name="declaration",
    )
    consent_text_version = models.CharField(max_length=50, blank=True, null=True)
    declared_by_name = models.CharField(max_length=200)
    declared_by_email = models.EmailField()
    consented_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "verification_declaration"

    def __str__(self):
        return (
            f"Declaration by {self.declared_by_email} "
            f"for {self.verification_request.reference_code}"
        )


# ---------------------------------------------------------------------------
# Verification Asset Photo
# ---------------------------------------------------------------------------


def _verification_photo_upload_path(instance, filename):
    return f"verification/{instance.request_asset_id}/photos/{filename}"


class VerificationAssetPhoto(models.Model):
    """Photos uploaded by the employee for a single asset during verification (max 3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_asset = models.ForeignKey(
        VerificationRequestAsset,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image = models.ImageField(upload_to=_verification_photo_upload_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "verification_asset_photo"

    def __str__(self):
        return f"Photo for {self.request_asset}"
