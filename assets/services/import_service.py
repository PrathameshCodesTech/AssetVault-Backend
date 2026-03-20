"""
Asset bulk import service.

Handles the creation of AssetImportJob records, row-level validation,
and synchronous row processing (Asset creation from valid rows).

Asset creation delegates to create_asset_with_details() in asset_service so
the bulk import path stays in sync with the single-asset register API.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime

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
_DECIMAL_FIELDS = {
    "purchase_value",
    "apc_fy_start",
    "acquisition_amount",
    "retirement_amount",
    "transfer_amount",
    "post_capitalization_amount",
    "current_apc_amount",
    "dep_fy_start",
    "dep_for_year",
    "dep_retirement_amount",
    "dep_transfer_amount",
    "write_ups_amount",
    "dep_post_cap_amount",
    "accumulated_depreciation_amount",
    "book_value_fy_start",
    "current_book_value",
}
_INTEGER_FIELDS = {"useful_life_in_periods"}
_DATE_FIELDS = {"capitalized_on", "deactivation_on"}
_FIELD_LABELS = {
    "asset_id": "Asset ID",
    "category_code": "Asset Type",
    "location_code": "Location",
    "entity_code": "Entity",
    "cost_center_code": "Cost Center",
    "supplier_name": "Supplier",
    "sub_type_code": "Sub Asset Type",
    "purchase_value": "Purchase Value",
    "capitalized_on": "Capitalized On",
    "deactivation_on": "Deactivation On",
    "useful_life_in_periods": "Useful Life in Periods",
    "apc_fy_start": "APC FY Start",
    "acquisition_amount": "Acquisition",
    "retirement_amount": "Retirement",
    "transfer_amount": "Transfer",
    "post_capitalization_amount": "Post-Capital.",
    "current_apc_amount": "Current APC",
    "dep_fy_start": "Dep. FY Start",
    "dep_for_year": "Dep. for Year",
    "dep_retirement_amount": "Dep. Retirement",
    "dep_transfer_amount": "Dep. Transfer",
    "write_ups_amount": "Write-ups",
    "dep_post_cap_amount": "Dep. Post-Cap.",
    "accumulated_depreciation_amount": "Accumulated Dep.",
    "book_value_fy_start": "Bk. Val. FY Start",
    "current_book_value": "Current Book Value",
}


def _as_text(value):
    return str(value or "").strip()


def _field_label(field_name: str) -> str:
    return _FIELD_LABELS.get(field_name, field_name.replace("_", " ").title())


def _can_parse_decimal(value):
    if not _as_text(value):
        return True
    try:
        Decimal(_as_text(value).replace(",", ""))
        return True
    except (InvalidOperation, ValueError, TypeError):
        return False


def _can_parse_int(value):
    if not _as_text(value):
        return True
    try:
        int(_as_text(value))
        return True
    except (ValueError, TypeError):
        return False


def _can_parse_date(value):
    text = _as_text(value)
    if not text:
        return True
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue
    return False


@transaction.atomic
def validate_import_rows(job: AssetImportJob, parsed_rows: list[dict]) -> None:
    """
    Validate parsed rows and persist AssetImportRow records.
    """
    rows_to_create: list[AssetImportRow] = []
    failed_rows = 0

    # Pre-load lookups for FK validation
    active_categories = list(AssetCategory.objects.filter(is_active=True).values("code", "name"))
    active_locations = list(LocationNode.objects.filter(is_active=True).values("code", "name"))
    active_entities = list(BusinessEntity.objects.filter(is_active=True).values("code", "name"))
    active_cost_centers = list(CostCenter.objects.filter(is_active=True).values("code", "name"))
    active_suppliers = list(Supplier.objects.filter(is_active=True).values("name"))
    active_sub_types = list(
        AssetSubType.objects.filter(is_active=True).select_related("category").values(
            "code", "name", "category__code", "category__name"
        )
    )

    category_codes = {row["code"] for row in active_categories}
    category_names = {row["name"] for row in active_categories}
    location_codes = {row["code"] for row in active_locations}
    location_names = {row["name"] for row in active_locations}
    entity_codes = {row["code"] for row in active_entities}
    entity_names = {row["name"] for row in active_entities}
    cost_center_codes = {row["code"] for row in active_cost_centers}
    cost_center_names = {row["name"] for row in active_cost_centers}
    supplier_names = {row["name"] for row in active_suppliers}
    seen_asset_ids: set[str] = set()

    for idx, raw_data in enumerate(parsed_rows):
        row_number = idx + 1
        errors = []
        asset_id = _as_text(raw_data.get("asset_id"))

        # Check required fields
        for field in _REQUIRED_FIELDS:
            if not _as_text(raw_data.get(field)):
                errors.append(f"Missing required field: {_field_label(field)}")

        if asset_id:
            if asset_id in seen_asset_ids:
                errors.append(f"Duplicate asset_id within file: {asset_id}")
            elif Asset.objects.filter(asset_id=asset_id).exists():
                errors.append(f"Asset ID already exists: {asset_id}")
            else:
                seen_asset_ids.add(asset_id)

        # Validate category lookup
        cat_code = _as_text(raw_data.get("category_code"))
        if cat_code and cat_code not in category_codes and cat_code not in category_names:
            errors.append(f"Unknown asset type: {cat_code}")

        # Validate location lookup
        loc_code = _as_text(raw_data.get("location_code"))
        if loc_code and loc_code not in location_codes and loc_code not in location_names:
            errors.append(f"Unknown location: {loc_code}")

        entity_code = _as_text(raw_data.get("entity_code"))
        if entity_code and entity_code not in entity_codes and entity_code not in entity_names:
            errors.append(f"Unknown entity: {entity_code}")

        cost_center_code = _as_text(raw_data.get("cost_center_code"))
        if (
            cost_center_code
            and cost_center_code not in cost_center_codes
            and cost_center_code not in cost_center_names
        ):
            errors.append(f"Unknown cost center: {cost_center_code}")

        supplier_name = _as_text(raw_data.get("supplier_name"))
        if supplier_name and supplier_name not in supplier_names:
            errors.append(f"Unknown supplier: {supplier_name}")

        sub_type_code = _as_text(raw_data.get("sub_type_code"))
        if sub_type_code:
            matching_sub_type = next(
                (
                    st for st in active_sub_types
                    if sub_type_code in {st["code"], st["name"]}
                ),
                None,
            )
            if matching_sub_type is None:
                errors.append(f"Unknown sub asset type: {sub_type_code}")
            elif cat_code and cat_code not in {
                matching_sub_type["category__code"],
                matching_sub_type["category__name"],
            }:
                errors.append(
                    f"Sub asset type '{sub_type_code}' does not belong to asset type '{cat_code}'"
                )

        for field in _DECIMAL_FIELDS:
            if not _can_parse_decimal(raw_data.get(field)):
                errors.append(
                    f"Invalid value for {_field_label(field)}: {raw_data.get(field)}"
                )

        for field in _INTEGER_FIELDS:
            if not _can_parse_int(raw_data.get(field)):
                errors.append(
                    f"Invalid whole number for {_field_label(field)}: {raw_data.get(field)}"
                )

        for field in _DATE_FIELDS:
            if not _can_parse_date(raw_data.get(field)):
                errors.append(
                    f"Invalid date for {_field_label(field)}: {raw_data.get(field)}. Use YYYY-MM-DD or DD/MM/YYYY."
                )

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
        return Decimal(str(value).replace(",", ""))
    except Exception:
        return None


def _safe_date(value):
    if not value:
        return None
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
            "useful_life": data.get("useful_life", "").strip() or None,
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
