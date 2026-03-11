import uuid

from django.core.exceptions import ValidationError
from django.db import models


def _submission_photo_upload_path(instance, filename):
    # Use the immutable submission UUID so the path never breaks
    return f"submissions/{instance.submission_id}/photos/{filename}"


# ---------------------------------------------------------------------------
# Field Submission
# ---------------------------------------------------------------------------

class FieldSubmission(models.Model):
    """A third-party operator's field submission.

    Two distinct use-cases share this model:
    - verification_existing  — operator scans / inspects an already-registered asset
    - new_asset_candidate    — operator reports something unregistered that should be added

    Clean() enforces which FK is required or forbidden per type.
    Status on this model is the current state; full history lives in SubmissionReview.
    """

    class SubmissionType(models.TextChoices):
        VERIFICATION_EXISTING = "verification_existing", "Verification — Existing Asset"
        NEW_ASSET_CANDIDATE = "new_asset_candidate", "New Asset Candidate"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CORRECTION_REQUESTED = "correction_requested", "Correction Requested"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    submitted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="field_submissions",
    )
    submission_type = models.CharField(
        max_length=30, choices=SubmissionType.choices, db_index=True
    )

    # Present for verification_existing; must be None for new_asset_candidate
    asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="field_submissions",
    )

    # Free-text fields populated for new_asset_candidate submissions
    asset_name = models.CharField(max_length=300, blank=True, null=True)
    serial_number = models.CharField(max_length=200, blank=True, null=True)
    asset_type_name = models.CharField(max_length=200, blank=True, null=True)

    location = models.ForeignKey(
        "locations.LocationNode",
        on_delete=models.PROTECT,
        related_name="field_submissions",
    )
    # Snapshot of the location at submission time for audit/display
    location_snapshot = models.JSONField(default=dict, blank=True)

    remarks = models.TextField(blank=True, null=True)

    status = models.CharField(
        max_length=25, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    submitted_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "submissions_field_submission"
        indexes = [
            models.Index(fields=["submitted_by"], name="sub_fs_submitted_by_idx"),
            models.Index(fields=["submission_type"], name="sub_fs_sub_type_idx"),
            models.Index(fields=["status"], name="sub_fs_status_idx"),
            models.Index(fields=["submitted_at"], name="sub_fs_submitted_at_idx"),
        ]

    def clean(self):
        # verification_existing must reference a registered asset
        if (
            self.submission_type == self.SubmissionType.VERIFICATION_EXISTING
            and not self.asset_id
        ):
            raise ValidationError(
                "A 'verification_existing' submission must reference an existing asset."
            )

        # new_asset_candidate describes something unregistered — FK must be absent
        if (
            self.submission_type == self.SubmissionType.NEW_ASSET_CANDIDATE
            and self.asset_id
        ):
            raise ValidationError(
                "A 'new_asset_candidate' submission must not link to an existing asset."
            )

        # new_asset_candidate must carry enough identifying data to be reviewable.
        # asset_name is the minimum — serial and type are encouraged but not required.
        if (
            self.submission_type == self.SubmissionType.NEW_ASSET_CANDIDATE
            and not (self.asset_name or "").strip()
        ):
            raise ValidationError(
                "A 'new_asset_candidate' submission must include at least an asset name."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.submission_type} by {self.submitted_by.email} [{self.status}]"


# ---------------------------------------------------------------------------
# Field Submission Photo
# ---------------------------------------------------------------------------

class FieldSubmissionPhoto(models.Model):
    """Photos attached to a field submission."""

    class ImageType(models.TextChoices):
        ASSET_PHOTO = "asset_photo", "Asset Photo"
        SUPPORTING_PHOTO = "supporting_photo", "Supporting Photo"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        FieldSubmission,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image = models.ImageField(upload_to=_submission_photo_upload_path)
    image_type = models.CharField(
        max_length=20, choices=ImageType.choices, default=ImageType.OTHER
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "submissions_field_submission_photo"

    def __str__(self):
        return f"Photo({self.image_type}) for submission {self.submission_id}"


# ---------------------------------------------------------------------------
# Submission Review
# ---------------------------------------------------------------------------

class SubmissionReview(models.Model):
    """An admin review action on a FieldSubmission.

    Append-only history — never overwritten. FieldSubmission.status reflects the
    latest decision; this model is the full audit trail of who reviewed what and when.

    PROTECT on submission: review records should not vanish if the submission is
    administratively cancelled — they may be needed for audit purposes.
    """

    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CORRECTION_REQUESTED = "correction_requested", "Correction Requested"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        FieldSubmission,
        # PROTECT: review history must survive even if submission is archived/soft-deleted
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="submission_reviews",
    )
    decision = models.CharField(max_length=25, choices=Decision.choices)
    review_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "submissions_submission_review"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["submission"], name="sub_sr_submission_idx"),
            models.Index(fields=["reviewed_by"], name="sub_sr_reviewed_by_idx"),
        ]

    def __str__(self):
        return f"{self.decision} on {self.submission_id} by {self.reviewed_by.email}"
