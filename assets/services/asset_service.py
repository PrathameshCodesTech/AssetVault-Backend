"""
Asset lifecycle service.

Handles core operations on Asset records: registration, assignment,
movement, and event logging. All mutating operations that touch more than
one table are wrapped in transactions.
"""
from django.db import transaction
from django.utils import timezone

from assets.models import Asset, AssetAssignment, AssetEvent, AssetFinancialDetail, AssetWFHDetail


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@transaction.atomic
def register_asset(
    *,
    asset_id: str,
    name: str,
    category,
    current_location,
    created_by=None,
    **kwargs,
) -> Asset:
    """
    Create a new Asset record and log a REGISTERED event.

    Positional-keyword arguments map directly to Asset fields. Any extra
    kwargs are forwarded to Asset() so callers can set optional fields
    (serial_number, tag_number, description, etc.) without changing this
    function's signature.

    Args:
        asset_id:         Human-readable identifier (e.g. "BANK-000281").
        name:             Display name for the asset.
        category:         AssetCategory instance (required FK).
        current_location: LocationNode instance (required FK).
        created_by:       accounts.User who registered the asset (optional).
        **kwargs:         Additional Asset field values.

    Returns:
        The newly created Asset.
    """
    asset = Asset.objects.create(
        asset_id=asset_id,
        name=name,
        category=category,
        current_location=current_location,
        created_by=created_by,
        **kwargs,
    )
    create_asset_event(
        asset,
        AssetEvent.EventType.REGISTERED,
        actor=created_by,
        description=f"Asset '{asset.asset_id}' registered.",
    )
    return asset


# ---------------------------------------------------------------------------
# Full asset creation with optional related details (shared by register API
# and bulk import)
# ---------------------------------------------------------------------------


@transaction.atomic
def create_asset_with_details(
    *,
    asset_id: str,
    name: str,
    category,
    current_location,
    created_by=None,
    financial_data: dict | None = None,
    wfh_data: dict | None = None,
    **kwargs,
) -> Asset:
    """
    Canonical shared creation path used by both the single-asset register API
    and the bulk import processor.

    Creates:
      1. Asset (via register_asset, which also logs REGISTERED event)
      2. AssetFinancialDetail if any non-None value is in financial_data
      3. AssetWFHDetail if any truthy value is in wfh_data; also sets is_wfh_asset=True

    financial_data keys (all optional, values are already resolved objects/scalars):
      sub_number, cost_center, internal_order, supplier,
      useful_life, useful_life_in_periods,
      apc_fy_start, acquisition_amount, retirement_amount, transfer_amount,
      post_capitalization_amount, current_apc_amount,
      dep_fy_start, dep_for_year, dep_retirement_amount, dep_transfer_amount,
      write_ups_amount, dep_post_cap_amount, accumulated_depreciation_amount,
      book_value_fy_start, current_book_value, deactivation_on

    wfh_data keys (all optional):
      wfh_uid, user_name, user_email, wfh_location_text
    """
    asset = register_asset(
        asset_id=asset_id,
        name=name,
        category=category,
        current_location=current_location,
        created_by=created_by,
        **kwargs,
    )

    if financial_data:
        if any(v is not None for v in financial_data.values()):
            AssetFinancialDetail.objects.create(asset=asset, **financial_data)

    if wfh_data:
        has_wfh = any(
            (v.strip() if isinstance(v, str) else v)
            for v in wfh_data.values()
        )
        if has_wfh:
            AssetWFHDetail.objects.create(
                asset=asset,
                **{k: v or None for k, v in wfh_data.items()},
            )
            if not asset.is_wfh_asset:
                asset.is_wfh_asset = True
                asset.save(update_fields=["is_wfh_asset"])

    return asset


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


@transaction.atomic
def assign_asset(
    asset: Asset,
    user,
    start_at,
    *,
    assigned_by=None,
    note: str | None = None,
) -> AssetAssignment:
    """
    Assign an asset to a user, closing any currently open assignment first.

    Steps:
    1. Close the existing open assignment (if any) by setting end_at = start_at.
    2. Create a new AssetAssignment with end_at = None.
    3. Update asset.assigned_to = user.
    4. Log a REASSIGNED event.

    Args:
        asset:       The Asset to assign.
        user:        accounts.User to assign the asset to.
        start_at:    datetime when the assignment begins.
        assigned_by: accounts.User who performed the assignment (optional).
        note:        Free-text note for the assignment record (optional).

    Returns:
        The newly created AssetAssignment.
    """
    # Close any existing open assignment at start_at, not timezone.now().
    # Using timezone.now() here produces wrong history for backdated or
    # scheduled assignments and can trip the model-level overlap validation
    # (an open row closed at "now" would overlap with a new row starting in
    # the past).  Closing at start_at creates a clean, non-overlapping handoff:
    #   old: [existing.start_at  →  start_at)
    #   new: [start_at           →  open)
    open_assignments = AssetAssignment.objects.filter(
        asset=asset, end_at__isnull=True
    )
    for existing in open_assignments:
        existing.end_at = start_at
        existing.save(update_fields=["end_at", "updated_at"])

    assignment = AssetAssignment.objects.create(
        asset=asset,
        user=user,
        start_at=start_at,
        assigned_by=assigned_by,
        note=note,
    )

    asset.assigned_to = user
    asset.save(update_fields=["assigned_to", "updated_at"])

    create_asset_event(
        asset,
        AssetEvent.EventType.REASSIGNED,
        actor=assigned_by,
        description=f"Asset assigned to '{user.email}'.",
    )
    return assignment


# ---------------------------------------------------------------------------
# Close assignment
# ---------------------------------------------------------------------------


@transaction.atomic
def close_assignment(
    assignment: AssetAssignment,
    end_at=None,
) -> AssetAssignment:
    """
    Close an open asset assignment.

    If the asset is currently assigned to the same user as the assignment,
    asset.assigned_to is cleared. Both the assignment and (if applicable)
    the asset are saved.

    Args:
        assignment: The AssetAssignment to close.
        end_at:     datetime to use as end_at. Defaults to timezone.now().

    Returns:
        The updated AssetAssignment.
    """
    assignment.end_at = end_at or timezone.now()
    assignment.save(update_fields=["end_at", "updated_at"])

    asset = assignment.asset
    if asset.assigned_to_id == assignment.user_id:
        asset.assigned_to = None
        asset.save(update_fields=["assigned_to", "updated_at"])

    return assignment


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------


@transaction.atomic
def move_asset(
    asset: Asset,
    to_location,
    *,
    actor=None,
    note: str | None = None,
) -> AssetEvent:
    """
    Move an asset to a new location and log a MOVED event.

    Args:
        asset:       The Asset to move.
        to_location: The destination LocationNode.
        actor:       accounts.User performing the move (optional).
        note:        Additional description text to include in the event (optional).

    Returns:
        The created AssetEvent.
    """
    from_location = asset.current_location

    asset.current_location = to_location
    asset.save(update_fields=["current_location", "updated_at"])

    description = (
        f"Moved from '{from_location.name}' to '{to_location.name}'."
    )
    if note:
        description = f"{description} Note: {note}"

    event = create_asset_event(
        asset,
        AssetEvent.EventType.MOVED,
        actor=actor,
        description=description,
        from_location=from_location,
        to_location=to_location,
    )
    return event


# ---------------------------------------------------------------------------
# Event creation helper
# ---------------------------------------------------------------------------


def create_asset_event(
    asset: Asset,
    event_type: str,
    *,
    actor=None,
    description: str = "",
    from_location=None,
    to_location=None,
    metadata: dict | None = None,
) -> AssetEvent:
    """
    Create and persist an AssetEvent row.

    This is a low-level helper. No transaction is applied here — the caller
    is responsible for wrapping in a transaction when atomicity is required.

    Args:
        asset:         The Asset the event relates to.
        event_type:    AssetEvent.EventType choice value (string).
        actor:         accounts.User who triggered the event (optional).
        description:   Human-readable description of the event.
        from_location: Origin LocationNode (optional, for MOVED events).
        to_location:   Destination LocationNode (optional, for MOVED events).
        metadata:      Extra JSON payload to store alongside the event (optional).

    Returns:
        The created AssetEvent.
    """
    return AssetEvent.objects.create(
        asset=asset,
        event_type=event_type,
        actor=actor,
        description=description,
        from_location=from_location,
        to_location=to_location,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# QR payload builder
# ---------------------------------------------------------------------------


def build_asset_qr_payload(asset: Asset) -> dict:
    """
    Build a minimal dict suitable for encoding into a QR code.

    The payload uses the immutable qr_uid as the primary identifier so the
    QR code remains valid even if the human-readable asset_id is corrected.

    No DB writes are performed.

    Args:
        asset: The Asset to build a payload for.

    Returns:
        Dict with keys: qr_uid, asset_id, name, category, current_location.
    """
    return {
        "qr_uid": str(asset.qr_uid),
        "asset_id": asset.asset_id,
        "name": asset.name,
        "category": asset.category.code if asset.category_id else None,
        "current_location": (
            asset.current_location.name if asset.current_location_id else None
        ),
    }
