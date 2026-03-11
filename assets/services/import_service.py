"""
Asset bulk import service.

Handles the creation of AssetImportJob records, row-level validation,
and synchronous row processing (Asset creation from valid rows).

Asset creation delegates to create_asset_with_details() in asset_service so
the bulk import path stays in sync with the single-asset register API.
"""
from django.db import transaction
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    AssetImportJob,
    AssetImportRow,
    AssetSubType,
    BusinessEntity,
    CostCenter,
    Supplier,
)
from locations.models import LocationNode


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------


def create_import_job(uploaded_by, source_file) -> AssetImportJob:
    """
    Create a new AssetImportJob record in UPLOADED state.
    """
    job = AssetImportJob.objects.create(
        uploaded_by=uploaded_by,
        source_file=source_file,
        status=AssetImportJob.Status.UPLOADED,
    )
    return job


# ---------------------------------------------------------------------------
# Row validation
# ---------------------------------------------------------------------------

# name is not required — it falls back to description or asset_id during processing
_REQUIRED_FIELDS = {"asset_id", "category_code", "location_code"}


@transaction.atomic
def validate_import_rows(job: AssetImportJob, parsed_rows: list[dict]) -> None:
    """
    Validate parsed rows and persist AssetImportRow records.
    """
    rows_to_create: list[AssetImportRow] = []
    failed_rows = 0

    # Pre-load lookups for FK validation
    category_codes = set(
        AssetCategory.objects.filter(is_active=True).values_list("code", flat=True)
    )
    category_names = set(
        AssetCategory.objects.filter(is_active=True).values_list("name", flat=True)
    )
    location_codes = set(
        LocationNode.objects.filter(is_active=True).values_list("code", flat=True)
    )
    location_names = set(
        LocationNode.objects.filter(is_active=True).values_list("name", flat=True)
    )

    for idx, raw_data in enumerate(parsed_rows):
        row_number = idx + 1
        errors = []

        # Check required fields
        for field in _REQUIRED_FIELDS:
            if not (raw_data.get(field) or "").strip():
                errors.append(f"Missing required field: {field}")

        # Validate category lookup
        cat_code = (raw_data.get("category_code") or "").strip()
        if cat_code and cat_code not in category_codes and cat_code not in category_names:
            errors.append(f"Unknown category: {cat_code}")

        # Validate location lookup
        loc_code = (raw_data.get("location_code") or "").strip()
        if loc_code and loc_code not in location_codes and loc_code not in location_names:
            errors.append(f"Unknown location: {loc_code}")

        if errors:
            status_val = AssetImportRow.Status.INVALID
            error_message = "; ".join(errors)
            failed_rows += 1
        else:
            status_val = AssetImportRow.Status.VALID
            error_message = None

        rows_to_create.append(
            AssetImportRow(
                job=job,
                row_number=row_number,
                raw_data=raw_data,
                status=status_val,
                error_message=error_message,
            )
        )

    AssetImportRow.objects.bulk_create(rows_to_create)

    job.total_rows = len(parsed_rows)
    job.failed_rows = failed_rows
    job.status = AssetImportJob.Status.VALIDATING
    job.save(update_fields=["total_rows", "failed_rows", "status", "updated_at"])


# ---------------------------------------------------------------------------
# Process job (synchronous implementation)
# ---------------------------------------------------------------------------


def _resolve_category(code_or_name):
    """Try to find category by code, then by name."""
    try:
        return AssetCategory.objects.get(code=code_or_name, is_active=True)
    except AssetCategory.DoesNotExist:
        try:
            return AssetCategory.objects.get(name__iexact=code_or_name, is_active=True)
        except AssetCategory.DoesNotExist:
            return None


def _resolve_location(code_or_name):
    """Try to find location by code, then by name."""
    try:
        return LocationNode.objects.get(code=code_or_name, is_active=True)
    except LocationNode.DoesNotExist:
        try:
            return LocationNode.objects.get(name__iexact=code_or_name, is_active=True)
        except (LocationNode.DoesNotExist, LocationNode.MultipleObjectsReturned):
            return None


def _resolve_sub_type(code_or_name, category):
    if not code_or_name or not category:
        return None
    try:
        return AssetSubType.objects.get(
            code=code_or_name, category=category, is_active=True
        )
    except AssetSubType.DoesNotExist:
        try:
            return AssetSubType.objects.get(
                name__iexact=code_or_name, category=category, is_active=True
            )
        except AssetSubType.DoesNotExist:
            return None


def _resolve_entity(code_or_name):
    if not code_or_name:
        return None
    try:
        return BusinessEntity.objects.get(code=code_or_name, is_active=True)
    except BusinessEntity.DoesNotExist:
        try:
            return BusinessEntity.objects.get(name__iexact=code_or_name, is_active=True)
        except BusinessEntity.DoesNotExist:
            return None


def _resolve_supplier(name):
    if not name:
        return None
    try:
        return Supplier.objects.get(name__iexact=name, is_active=True)
    except Supplier.DoesNotExist:
        return None


def _resolve_cost_center(code_or_name):
    if not code_or_name:
        return None
    try:
        return CostCenter.objects.get(code=code_or_name, is_active=True)
    except CostCenter.DoesNotExist:
        try:
            return CostCenter.objects.get(name__iexact=code_or_name, is_active=True)
        except CostCenter.DoesNotExist:
            return None


def _safe_decimal(value):
    if not value:
        return None
    try:
        from decimal import Decimal
        return Decimal(str(value).replace(",", ""))
    except Exception:
        return None


def _safe_date(value):
    if not value:
        return None
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _safe_int(value):
    if not value:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def process_import_job(job: AssetImportJob, created_by=None) -> dict:
    """
    Iterate VALID rows and create Asset records synchronously via
    create_asset_with_details() — the same shared path as the single-asset
    register API.

    Returns dict with success_rows and failed_rows counts.
    """
    from assets.services.asset_service import create_asset_with_details

    job.started_at = timezone.now()
    job.save(update_fields=["started_at", "updated_at"])

    valid_rows = list(
        job.rows.filter(status=AssetImportRow.Status.VALID).order_by("row_number")
    )

    success_count = 0
    fail_count = 0

    for row in valid_rows:
        data = row.raw_data

        category = _resolve_category(data.get("category_code", ""))
        location = _resolve_location(data.get("location_code", ""))

        if not category or not location:
            row.status = AssetImportRow.Status.INVALID
            errors = []
            if not category:
                errors.append(f"Category not found: {data.get('category_code')}")
            if not location:
                errors.append(f"Location not found: {data.get('location_code')}")
            row.error_message = "; ".join(errors)
            row.save(update_fields=["status", "error_message", "updated_at"])
            fail_count += 1
            continue

        asset_id = data.get("asset_id", "").strip()
        # name falls back to description or asset_id for backward compatibility
        name = (
            data.get("name", "").strip()
            or data.get("description", "").strip()
            or asset_id
        )
        description = data.get("description", "").strip() or None

        # Check for duplicate asset_id
        if Asset.objects.filter(asset_id=asset_id).exists():
            row.status = AssetImportRow.Status.SKIPPED
            row.error_message = f"Asset ID '{asset_id}' already exists."
            row.save(update_fields=["status", "error_message", "updated_at"])
            fail_count += 1
            continue

        sub_type = _resolve_sub_type(data.get("sub_type_code", ""), category)
        entity = _resolve_entity(data.get("entity_code", ""))

        # Build financial data dict (resolved objects, ready for model creation)
        financial_data = {
            "sub_number": data.get("sub_number", "") or None,
            "cost_center": _resolve_cost_center(data.get("cost_center_code", "")),
            "internal_order": data.get("internal_order", "") or None,
            "supplier": _resolve_supplier(data.get("supplier_name", "")),
            "useful_life": _safe_int(data.get("useful_life")),
            "useful_life_in_periods": _safe_int(data.get("useful_life_in_periods")),
            "apc_fy_start": _safe_decimal(data.get("apc_fy_start")),
            "acquisition_amount": _safe_decimal(data.get("acquisition_amount")),
            "retirement_amount": _safe_decimal(data.get("retirement_amount")),
            "transfer_amount": _safe_decimal(data.get("transfer_amount")),
            "post_capitalization_amount": _safe_decimal(data.get("post_capitalization_amount")),
            "current_apc_amount": _safe_decimal(data.get("current_apc_amount")),
            "dep_fy_start": _safe_decimal(data.get("dep_fy_start")),
            "dep_for_year": _safe_decimal(data.get("dep_for_year")),
            "dep_retirement_amount": _safe_decimal(data.get("dep_retirement_amount")),
            "dep_transfer_amount": _safe_decimal(data.get("dep_transfer_amount")),
            "write_ups_amount": _safe_decimal(data.get("write_ups_amount")),
            "dep_post_cap_amount": _safe_decimal(data.get("dep_post_cap_amount")),
            "accumulated_depreciation_amount": _safe_decimal(data.get("accumulated_depreciation_amount")),
            "book_value_fy_start": _safe_decimal(data.get("book_value_fy_start")),
            "current_book_value": _safe_decimal(data.get("current_book_value")),
            "deactivation_on": _safe_date(data.get("deactivation_on")),
        }

        # WFH data — keys match AssetWFHDetail field names exactly
        wfh_data = {
            "wfh_uid": data.get("wfh_uid", "").strip() or None,
            "user_name": data.get("user_name", "").strip() or None,
            "user_email": data.get("user_email", "").strip() or None,
            "wfh_location_text": data.get("wfh_location_text", "").strip() or None,
        }

        try:
            asset = create_asset_with_details(
                asset_id=asset_id,
                name=name,
                category=category,
                current_location=location,
                created_by=created_by,
                description=description,
                sub_type=sub_type,
                business_entity=entity,
                sub_location_text=data.get("sub_location_text", "") or None,
                serial_number=data.get("serial_number", "") or None,
                tag_number=data.get("tag_number", "") or None,
                asset_class=data.get("asset_class", "") or None,
                currency_code=data.get("currency_code", "") or None,
                purchase_value=_safe_decimal(data.get("purchase_value")),
                capitalized_on=_safe_date(data.get("capitalized_on")),
                financial_data=financial_data,
                wfh_data=wfh_data,
            )

            row.status = AssetImportRow.Status.IMPORTED
            row.asset = asset
            row.error_message = None
            row.save(update_fields=["status", "asset", "error_message", "updated_at"])
            success_count += 1

        except Exception as exc:
            row.status = AssetImportRow.Status.INVALID
            row.error_message = str(exc)[:500]
            row.save(update_fields=["status", "error_message", "updated_at"])
            fail_count += 1

    # Update job
    job.success_rows = success_count
    job.failed_rows = job.failed_rows + fail_count
    job.status = AssetImportJob.Status.PROCESSED
    job.completed_at = timezone.now()
    job.save(
        update_fields=[
            "success_rows",
            "failed_rows",
            "status",
            "completed_at",
            "updated_at",
        ]
    )

    return {"success_rows": success_count, "failed_rows": fail_count}
