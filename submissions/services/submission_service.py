"""
Field submission service.

Handles the lifecycle of FieldSubmission records: creation, review
(approve / reject / correction-request), and candidate-to-asset conversion.

All state-changing operations that touch more than one table are wrapped
in database transactions.
"""
from django.db import transaction
from django.utils import timezone

from assets.models import Asset, AssetCategory
from assets.services.asset_service import register_asset
from locations.models import LocationNode
from submissions.models import FieldSubmission, SubmissionReview


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@transaction.atomic
def create_submission(
    submitted_by,
    submission_type: str,
    location,
    submitted_at,
    *,
    asset=None,
    asset_name: str | None = None,
    serial_number: str | None = None,
    asset_type_name: str | None = None,
    remarks: str | None = None,
) -> FieldSubmission:
    """
    Create a new FieldSubmission.

    Captures a location_snapshot from the live LocationNode at the time of
    submission so that display/audit remains stable even if the node is later
    renamed or restructured.

    Args:
        submitted_by:    accounts.User submitting the form (required).
        submission_type: FieldSubmission.SubmissionType choice string.
        location:        locations.LocationNode instance (required FK).
        submitted_at:    datetime when the submission was made (set by caller).
        asset:           assets.Asset FK — required for verification_existing,
                         must be None for new_asset_candidate.
        asset_name:      Free-text name — required for new_asset_candidate.
        serial_number:   Optional serial number string.
        asset_type_name: Optional asset type description string.
        remarks:         Optional free-text remarks.

    Returns:
        The newly created FieldSubmission with status PENDING.
    """
    location_snapshot = {
        "id": str(location.pk),
        "code": location.code,
        "name": location.name,
        "path": location.path,
        "location_type_code": (
            location.location_type.code if location.location_type_id else None
        ),
        "location_type_name": (
            location.location_type.name if location.location_type_id else None
        ),
    }

    submission = FieldSubmission.objects.create(
        submitted_by=submitted_by,
        submission_type=submission_type,
        location=location,
        location_snapshot=location_snapshot,
        submitted_at=submitted_at,
        asset=asset,
        asset_name=asset_name,
        serial_number=serial_number,
        asset_type_name=asset_type_name,
        remarks=remarks,
        status=FieldSubmission.Status.PENDING,
    )
    return submission


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


@transaction.atomic
def approve_submission(
    submission: FieldSubmission,
    reviewed_by,
    *,
    notes: str | None = None,
) -> SubmissionReview:
    """
    Approve a pending FieldSubmission.

    Validates that the submission is in PENDING state, creates a SubmissionReview
    with decision=APPROVED, and updates the submission status and reviewed_at.

    Args:
        submission:  The FieldSubmission to approve.
        reviewed_by: accounts.User performing the review.
        notes:       Optional review notes.

    Returns:
        The created SubmissionReview.

    Raises:
        ValueError: If the submission is not in PENDING state.
    """
    if submission.status != FieldSubmission.Status.PENDING:
        raise ValueError(
            f"Cannot approve a submission with status '{submission.status}'. "
            f"Only PENDING submissions can be approved."
        )

    review = SubmissionReview.objects.create(
        submission=submission,
        reviewed_by=reviewed_by,
        decision=SubmissionReview.Decision.APPROVED,
        review_notes=notes,
    )

    submission.status = FieldSubmission.Status.APPROVED
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["status", "reviewed_at", "updated_at"])

    return review


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


@transaction.atomic
def reject_submission(
    submission: FieldSubmission,
    reviewed_by,
    *,
    notes: str | None = None,
) -> SubmissionReview:
    """
    Reject a pending or correction-requested FieldSubmission.

    Validates that the submission is in PENDING or CORRECTION_REQUESTED state,
    creates a SubmissionReview with decision=REJECTED, and updates the submission.

    Args:
        submission:  The FieldSubmission to reject.
        reviewed_by: accounts.User performing the review.
        notes:       Optional review notes.

    Returns:
        The created SubmissionReview.

    Raises:
        ValueError: If the submission is not in a rejectable state.
    """
    rejectable_statuses = {
        FieldSubmission.Status.PENDING,
        FieldSubmission.Status.CORRECTION_REQUESTED,
    }
    if submission.status not in rejectable_statuses:
        raise ValueError(
            f"Cannot reject a submission with status '{submission.status}'. "
            f"Only PENDING or CORRECTION_REQUESTED submissions can be rejected."
        )

    review = SubmissionReview.objects.create(
        submission=submission,
        reviewed_by=reviewed_by,
        decision=SubmissionReview.Decision.REJECTED,
        review_notes=notes,
    )

    submission.status = FieldSubmission.Status.REJECTED
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["status", "reviewed_at", "updated_at"])

    return review


# ---------------------------------------------------------------------------
# Request correction
# ---------------------------------------------------------------------------


@transaction.atomic
def request_submission_correction(
    submission: FieldSubmission,
    reviewed_by,
    *,
    notes: str | None = None,
) -> SubmissionReview:
    """
    Request a correction on a pending FieldSubmission.

    Validates that the submission is in PENDING state, creates a SubmissionReview
    with decision=CORRECTION_REQUESTED, and updates the submission.

    Args:
        submission:  The FieldSubmission to flag for correction.
        reviewed_by: accounts.User performing the review.
        notes:       Optional notes describing what needs to be corrected.

    Returns:
        The created SubmissionReview.

    Raises:
        ValueError: If the submission is not in PENDING state.
    """
    if submission.status != FieldSubmission.Status.PENDING:
        raise ValueError(
            f"Cannot request a correction for a submission with status "
            f"'{submission.status}'. Only PENDING submissions can have "
            f"corrections requested."
        )

    review = SubmissionReview.objects.create(
        submission=submission,
        reviewed_by=reviewed_by,
        decision=SubmissionReview.Decision.CORRECTION_REQUESTED,
        review_notes=notes,
    )

    submission.status = FieldSubmission.Status.CORRECTION_REQUESTED
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["status", "reviewed_at", "updated_at"])

    return review


# ---------------------------------------------------------------------------
# Candidate → Asset conversion
# ---------------------------------------------------------------------------


@transaction.atomic
def convert_candidate_to_asset(
    submission: FieldSubmission,
    *,
    asset_id: str,
    name: str,
    category_id,
    location_id,
    serial_number: str | None = None,
    description: str | None = None,
    created_by=None,
) -> Asset:
    """
    Convert an approved new_asset_candidate submission into a real Asset.

    The submission must be APPROVED and of type NEW_ASSET_CANDIDATE.
    Uses ``register_asset`` so the standard REGISTERED event is logged.

    After creation the submission status is set to APPROVED (already is) and
    a review note is appended documenting the conversion.

    Args:
        submission:    The FieldSubmission to convert.
        asset_id:      Human-readable asset identifier for the new Asset.
        name:          Display name.
        category_id:   UUID of the AssetCategory.
        location_id:   UUID of the LocationNode.
        serial_number: Optional serial number.
        description:   Optional description.
        created_by:    accounts.User performing the conversion.

    Returns:
        The newly created Asset.

    Raises:
        ValueError: If the submission is not an approved new_asset_candidate.
    """
    if submission.submission_type != FieldSubmission.SubmissionType.NEW_ASSET_CANDIDATE:
        raise ValueError("Only new_asset_candidate submissions can be converted.")

    if submission.status != FieldSubmission.Status.APPROVED:
        raise ValueError(
            f"Submission must be APPROVED to convert. Current: {submission.status}"
        )

    category = AssetCategory.objects.get(pk=category_id)
    location = LocationNode.objects.get(pk=location_id)

    kwargs = {}
    if serial_number:
        kwargs["serial_number"] = serial_number
    if description:
        kwargs["description"] = description

    asset = register_asset(
        asset_id=asset_id,
        name=name,
        category=category,
        current_location=location,
        created_by=created_by,
        **kwargs,
    )

    SubmissionReview.objects.create(
        submission=submission,
        reviewed_by=created_by,
        decision=SubmissionReview.Decision.APPROVED,
        review_notes=f"Converted to asset {asset.asset_id}.",
    )

    return asset
