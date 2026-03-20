"""
Verification request service.

Handles the lifecycle of VerificationRequest objects:
creation, asset snapshotting, resend, cancellation, and submission.

Email dispatch and Celery task integration are explicitly excluded from this
module — callers are responsible for triggering those side-effects after
calling the functions here.
"""
import secrets
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from verification.models import (
    AssetVerificationResponse,
    VerificationRequest,
    VerificationRequestAsset,
)

if TYPE_CHECKING:
    from assets.models import Asset, AssetQuerySet


def _generate_public_token() -> str:
    """Generate a new URL-safe public token for a verification request link."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@transaction.atomic
def create_verification_request(
    cycle,
    employee,
    *,
    requested_by=None,
    location_scope=None,
    reference_code: str,
) -> VerificationRequest:
    """
    Create a new VerificationRequest for an employee within a cycle.

    Validates that no active (pending / opened / otp_verified) request already
    exists for this employee+cycle combination. Raises ValueError if one does.

    Args:
        cycle:           VerificationCycle instance.
        employee:        accounts.User instance to be verified.
        requested_by:    accounts.User who initiated the request (optional).
        location_scope:  locations.LocationNode to restrict scope (optional).
        reference_code:  Human-readable reference code (e.g. "VER-2526-00042").
                         Must be unique — caller is responsible for generating it.

    Returns:
        The newly created VerificationRequest with status PENDING.
    """
    # Guard: only one active request per employee per cycle
    active_qs = VerificationRequest.objects.filter(
        cycle=cycle,
        employee=employee,
        status__in=list(VerificationRequest.ACTIVE_STATUSES),
    )
    if active_qs.exists():
        raise ValueError(
            f"Employee '{employee.email}' already has an active verification request "
            f"in cycle '{cycle.code}'. Cancel or expire it before issuing a new one."
        )

    verification_request = VerificationRequest.objects.create(
        cycle=cycle,
        employee=employee,
        requested_by=requested_by,
        location_scope=location_scope,
        reference_code=reference_code,
        public_token=_generate_public_token(),
        status=VerificationRequest.Status.PENDING,
    )
    return verification_request


# ---------------------------------------------------------------------------
# Snapshot assets
# ---------------------------------------------------------------------------


def snapshot_request_assets(
    verification_request: VerificationRequest,
    asset_queryset,
) -> list[VerificationRequestAsset]:
    """
    Create VerificationRequestAsset snapshot rows for each asset in the queryset.

    Snapshot fields are captured from the live asset at call-time. Subsequent
    changes to the Asset record do not affect what the employee sees in the
    verification flow.

    Args:
        verification_request: The parent VerificationRequest.
        asset_queryset:        QuerySet (or iterable) of assets.Asset.Asset instances.

    Returns:
        List of created VerificationRequestAsset instances.
    """
    rows = []
    for idx, asset in enumerate(asset_queryset):
        # Build a compact snapshot payload with all useful fields
        snapshot_payload = {
            "asset_id": asset.asset_id,
            "name": asset.name,
            "serial_number": asset.serial_number,
            "tag_number": asset.tag_number,
            "status": asset.status,
            "category_code": asset.category.code if asset.category_id else None,
            "category_name": asset.category.name if asset.category_id else None,
            "location_name": asset.current_location.name if asset.current_location_id else None,
            "sub_location_text": asset.sub_location_text,
        }
        rows.append(
            VerificationRequestAsset(
                verification_request=verification_request,
                asset=asset,
                snapshot_asset_id=asset.asset_id,
                snapshot_name=asset.name,
                snapshot_serial_number=asset.serial_number,
                snapshot_category_name=(
                    asset.category.name if asset.category_id else None
                ),
                snapshot_location_name=(
                    asset.current_location.name if asset.current_location_id else None
                ),
                snapshot_payload=snapshot_payload,
                sort_order=idx,
            )
        )

    created = VerificationRequestAsset.objects.bulk_create(rows)
    return created


# ---------------------------------------------------------------------------
# Resend
# ---------------------------------------------------------------------------


def resend_verification_request(
    verification_request: VerificationRequest,
    *,
    requested_by=None,
) -> VerificationRequest:
    """
    Resend a verification request that is still in PENDING or OPENED state.

    Generates a new public_token (invalidating the old link) and updates sent_at
    to the current time.

    Args:
        verification_request: The VerificationRequest to resend.
        requested_by:         accounts.User performing the resend (optional, for audit).

    Returns:
        The updated VerificationRequest.

    Raises:
        ValueError: If the request is not in a resendable state.
    """
    resendable_statuses = {
        VerificationRequest.Status.PENDING,
        VerificationRequest.Status.OPENED,
    }
    if verification_request.status not in resendable_statuses:
        raise ValueError(
            f"Cannot resend a request with status '{verification_request.status}'. "
            f"Only PENDING or OPENED requests can be resent."
        )

    verification_request.public_token = _generate_public_token()
    verification_request.sent_at = timezone.now()
    verification_request.save(update_fields=["public_token", "sent_at", "updated_at"])

    # PLACEHOLDER: Trigger email dispatch here.
    # Example: send_verification_email.delay(verification_request.pk)

    return verification_request


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


def cancel_verification_request(
    verification_request: VerificationRequest,
    *,
    cancelled_by=None,
) -> VerificationRequest:
    """
    Cancel a verification request that has not yet reached a terminal state.

    Terminal states (SUBMITTED, CANCELLED) cannot be cancelled again.

    Args:
        verification_request: The VerificationRequest to cancel.
        cancelled_by:         accounts.User performing the cancellation (optional).

    Returns:
        The updated VerificationRequest with status CANCELLED.

    Raises:
        ValueError: If the request is already in a terminal state.
    """
    terminal_statuses = {
        VerificationRequest.Status.SUBMITTED,
        VerificationRequest.Status.CANCELLED,
    }
    if verification_request.status in terminal_statuses:
        raise ValueError(
            f"Cannot cancel a request with status '{verification_request.status}'. "
            f"It is already in a terminal state."
        )

    verification_request.status = VerificationRequest.Status.CANCELLED
    verification_request.save(update_fields=["status", "updated_at"])
    return verification_request


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_verification_request(
    verification_request: VerificationRequest,
) -> VerificationRequest:
    """
    Submit a verification request through the employee public verification flow.

    Validates that the request is in an active employee-actionable state,
    marks it SUBMITTED, and propagates asset reconciliation statuses based
    on the employee's responses.

    Args:
        verification_request: The VerificationRequest to submit.

    Returns:
        The updated VerificationRequest with status SUBMITTED.

    Raises:
        ValueError: If the request is not in an employee-submittable state.
    """
    submittable_statuses = {
        VerificationRequest.Status.OPENED,
        VerificationRequest.Status.CORRECTION_REQUESTED,
    }
    if verification_request.status not in submittable_statuses:
        raise ValueError(
            f"Cannot submit a request with status '{verification_request.status}'. "
            f"Only OPENED or CORRECTION_REQUESTED requests can be submitted."
        )

    verification_request.status = VerificationRequest.Status.SUBMITTED
    verification_request.submitted_at = timezone.now()
    verification_request.save(update_fields=["status", "submitted_at", "updated_at"])

    _update_asset_reconciliation_statuses(verification_request)

    return verification_request


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _update_asset_reconciliation_statuses(
    verification_request: VerificationRequest,
) -> None:
    """
    Propagate employee responses back to the live Asset reconciliation_status.

    For each VerificationRequestAsset that has a response:
    - VERIFIED        → asset.reconciliation_status = VERIFIED
    - ISSUE_REPORTED  → asset.reconciliation_status = DISCREPANCY

    Uses bulk_update to minimise DB round-trips.
    """
    from assets.models import Asset  # local import to avoid circular dependency

    request_assets = (
        verification_request.request_assets
        .select_related("response", "asset")
        .filter(response__isnull=False)
    )

    assets_to_update: list[Asset] = []
    for ra in request_assets:
        response = ra.response
        asset = ra.asset

        if response.response == AssetVerificationResponse.Response.VERIFIED:
            asset.reconciliation_status = Asset.ReconciliationStatus.VERIFIED
            assets_to_update.append(asset)
        elif response.response == AssetVerificationResponse.Response.ISSUE_REPORTED:
            asset.reconciliation_status = Asset.ReconciliationStatus.DISCREPANCY
            assets_to_update.append(asset)

    if assets_to_update:
        Asset.objects.bulk_update(assets_to_update, ["reconciliation_status"])
