"""
Vendor organization and vendor verification request models.

This module is entirely separate from the employee verification flow
(verification app) and from free-form field submissions (submissions app).
"""
import datetime
import uuid

from django.db import models


def _asset_photo_upload_path(instance, filename):
    return (
        f"vendor_requests/{instance.request_asset.request_id}/"
        f"{instance.request_asset.asset_id}/{filename}"
    )


# ---------------------------------------------------------------------------
# Vendor Organization
# ---------------------------------------------------------------------------

class VendorOrganization(models.Model):
    """A named third-party vendor / contractor organization."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=300)
    contact_email = models.EmailField(blank=True, null=True)
    contact_phone = models.CharField(max_length=30, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vendors_vendor_organization"
        ordering = ("name",)

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Vendor User Assignment
# ---------------------------------------------------------------------------

class VendorUserAssignment(models.Model):
    """Links a platform user account to a vendor organization.

    A user may belong to at most one vendor organization (enforced by unique_together).
    Soft-deactivate with is_active=False rather than deleting to preserve audit history.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(
        VendorOrganization,
        on_delete=models.CASCADE,
        related_name="user_assignments",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="vendor_assignments",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vendors_vendor_user_assignment"
        # One active membership per user across all vendors
        unique_together = (("vendor", "user"),)

    def __str__(self):
        return f"{self.user.email} → {self.vendor.name}"


# ---------------------------------------------------------------------------
# Vendor Verification Request (package)
# ---------------------------------------------------------------------------

class VendorVerificationRequest(models.Model):
    """A batch of unmapped assets sent to a specific vendor for physical verification.

    One request belongs to exactly one vendor.
    Assets are attached via VendorVerificationRequestAsset (junction model).
    Status mirrors the employee VerificationRequest lifecycle conceptually,
    but lives in a completely separate table and code path.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent to Vendor"
        IN_PROGRESS = "in_progress", "In Progress"
        SUBMITTED = "submitted", "Submitted by Vendor"
        CORRECTION_REQUESTED = "correction_requested", "Correction Requested"
        APPROVED = "approved", "Approved"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference_code = models.CharField(max_length=100, unique=True)

    vendor = models.ForeignKey(
        VendorOrganization,
        on_delete=models.PROTECT,
        related_name="verification_requests",
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="created_vendor_requests",
    )
    location_scope = models.ForeignKey(
        "locations.LocationNode",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vendor_requests",
    )

    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    notes = models.TextField(blank=True, null=True)           # admin notes visible to vendor
    review_notes = models.TextField(blank=True, null=True)    # correction/rejection reason

    sent_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_vendor_requests",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vendors_vendor_verification_request"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["vendor"], name="vendors_vvr_vendor_idx"),
            models.Index(fields=["status"], name="vendors_vvr_status_idx"),
            models.Index(fields=["created_at"], name="vendors_vvr_created_at_idx"),
        ]

    def __str__(self):
        return f"{self.reference_code} → {self.vendor.name} [{self.status}]"

    @classmethod
    def generate_reference_code(cls):
        prefix = datetime.datetime.utcnow().strftime("VVR-%Y%m%d")
        count = cls.objects.filter(reference_code__startswith=prefix).count()
        return f"{prefix}-{count + 1:04d}"


# ---------------------------------------------------------------------------
# Vendor Verification Request Asset (per-asset response)
# ---------------------------------------------------------------------------

class VendorVerificationRequestAsset(models.Model):
    """An asset included in a vendor verification request.

    Captures a snapshot of the asset at request creation time,
    plus the vendor's per-asset response and the admin's per-asset decision.
    """

    class ResponseStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed Present"
        ISSUE_REPORTED = "issue_reported", "Issue Reported"

    class AdminDecision(models.TextChoices):
        PENDING_REVIEW = "pending_review", "Pending Review"
        APPROVED = "approved", "Approved"
        CORRECTION_REQUIRED = "correction_required", "Correction Required"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        VendorVerificationRequest,
        on_delete=models.CASCADE,
        related_name="request_assets",
    )
    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.PROTECT,
        related_name="vendor_request_assets",
    )

    # Snapshot at request creation (so the record remains readable even if asset is edited)
    asset_id_snapshot = models.CharField(max_length=100)
    asset_name_snapshot = models.CharField(max_length=300)
    asset_location_snapshot = models.CharField(max_length=500, blank=True)

    # Vendor response fields
    response_status = models.CharField(
        max_length=20,
        choices=ResponseStatus.choices,
        default=ResponseStatus.PENDING,
        db_index=True,
    )
    response_notes = models.TextField(blank=True, null=True)
    observed_location = models.ForeignKey(
        "locations.LocationNode",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vendor_observations",
    )
    responded_at = models.DateTimeField(null=True, blank=True)

    # Admin per-asset decision (written during review)
    admin_decision = models.CharField(
        max_length=20,
        choices=AdminDecision.choices,
        default=AdminDecision.PENDING_REVIEW,
        db_index=True,
    )

    class Meta:
        db_table = "vendors_vendor_request_asset"
        unique_together = (("request", "asset"),)

    def __str__(self):
        return f"{self.asset_id_snapshot} in {self.request.reference_code}"


# ---------------------------------------------------------------------------
# Vendor Request Asset Photo
# ---------------------------------------------------------------------------

class VendorRequestAssetPhoto(models.Model):
    """Photo uploaded by a vendor for a specific asset inside a request."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_asset = models.ForeignKey(
        VendorVerificationRequestAsset,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image = models.ImageField(upload_to=_asset_photo_upload_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vendors_request_asset_photo"

    def __str__(self):
        return f"Photo for {self.request_asset}"
