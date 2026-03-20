import csv
import io

from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.permissions import permission_required
from assets.models import AssetImportJob, AssetImportRow
from assets.serializers import AssetImportJobSerializer, AssetImportRowSerializer
from assets.services.import_service import (
    create_import_job,
    process_import_job,
    validate_import_rows,
)

__all__ = [
    "BulkUploadPreviewView",
    "BulkUploadProcessView",
    "ImportJobDetailView",
    "ImportJobRowsView",
]

# Column name mapping: template header -> internal field name
COLUMN_MAP = {
    "entity": "entity_code",
    "asset id": "asset_id",
    # Distinct name vs description columns (old templates had only "Asset Description" mapped to name)
    "asset name": "name",
    "asset description": "description",
    "serial number": "serial_number",
    "sub number": "sub_number",
    "tag number": "tag_number",
    "asset class": "asset_class",
    "asset type": "category_code",
    "sub asset type": "sub_type_code",
    "cost center": "cost_center_code",
    "int. order": "internal_order",
    "supplier": "supplier_name",
    "currency": "currency_code",
    "purchase value": "purchase_value",
    "useful life": "useful_life",
    "useful life in periods": "useful_life_in_periods",
    "capitalized on": "capitalized_on",
    "location": "location_code",
    "sub location": "sub_location_text",
    "apc fy start": "apc_fy_start",
    "acquisition": "acquisition_amount",
    "retirement": "retirement_amount",
    "transfer": "transfer_amount",
    "post-capital.": "post_capitalization_amount",
    "current apc": "current_apc_amount",
    "dep. fy start": "dep_fy_start",
    "dep. for year": "dep_for_year",
    "dep. retirement": "dep_retirement_amount",
    "dep. transfer": "dep_transfer_amount",
    "write-ups": "write_ups_amount",
    "dep. post-cap.": "dep_post_cap_amount",
    "accumulated dep.": "accumulated_depreciation_amount",
    "bk. val. fy start": "book_value_fy_start",
    "current book value": "current_book_value",
    "deactivation on": "deactivation_on",
    "wfh uid": "wfh_uid",
    "wfh user name": "user_name",
    "wfh user email": "user_email",
    "wfh location": "wfh_location_text",
}


def _parse_file(uploaded_file):
    """Parse CSV or XLSX file into list of row dicts."""
    filename = uploaded_file.name.lower()
    rows = []

    if filename.endswith(".csv"):
        content = uploaded_file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            mapped = {}
            for header, value in row.items():
                key = COLUMN_MAP.get(header.strip().lower(), header.strip().lower().replace(" ", "_"))
                mapped[key] = (value or "").strip()
            rows.append(mapped)

    elif filename.endswith(".xlsx"):
        import openpyxl

        wb = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
        ws = wb.active
        headers = []
        for idx, cell_row in enumerate(ws.iter_rows(values_only=True)):
            if idx == 0:
                headers = [str(c or "").strip() for c in cell_row]
                continue
            if not any(cell_row):
                continue
            mapped = {}
            for col_idx, value in enumerate(cell_row):
                if col_idx < len(headers):
                    header = headers[col_idx]
                    key = COLUMN_MAP.get(header.lower(), header.lower().replace(" ", "_"))
                    mapped[key] = str(value).strip() if value is not None else ""
            rows.append(mapped)
        wb.close()
    else:
        raise ValueError(
            "Unsupported file format. Please upload a CSV or XLSX file."
        )

    return rows


class BulkUploadPreviewView(APIView):
    """POST /api/assets/upload/preview/ — parse file and validate rows."""

    permission_classes = [IsAuthenticated, permission_required("asset.import")]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response(
                {"detail": "No file provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parsed_rows = _parse_file(uploaded_file)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            return Response(
                {"detail": f"Failed to parse file: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not parsed_rows:
            return Response(
                {"detail": "File contains no data rows."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create import job
        job = create_import_job(uploaded_by=request.user, source_file=uploaded_file)
        validate_import_rows(job, parsed_rows)

        # Build preview
        rows_qs = job.rows.all().order_by("row_number")
        errors = []
        for row in rows_qs:
            if row.status == AssetImportRow.Status.INVALID:
                errors.append({"row": row.row_number, "message": row.error_message})

        return Response(
            {
                "job_id": str(job.pk),
                "total_rows": job.total_rows,
                "valid_rows": job.total_rows - job.failed_rows,
                "failed_rows": job.failed_rows,
                "errors": errors,
                "preview": AssetImportRowSerializer(rows_qs[:20], many=True).data,
            },
            status=status.HTTP_200_OK,
        )


class BulkUploadProcessView(APIView):
    """POST /api/assets/upload/process/ — process valid rows of an import job."""

    permission_classes = [IsAuthenticated, permission_required("asset.import")]

    def post(self, request):
        job_id = request.data.get("job_id")
        if not job_id:
            return Response(
                {"detail": "job_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            job = AssetImportJob.objects.get(pk=job_id)
        except AssetImportJob.DoesNotExist:
            return Response(
                {"detail": "Import job not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if job.status not in (
            AssetImportJob.Status.UPLOADED,
            AssetImportJob.Status.VALIDATING,
        ):
            return Response(
                {"detail": f"Job is already in '{job.status}' state."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = process_import_job(job, created_by=request.user)
        except Exception as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "job_id": str(job.pk),
                "status": job.status,
                "success_rows": result.get("success_rows", 0),
                "failed_rows": result.get("failed_rows", 0),
            },
            status=status.HTTP_200_OK,
        )


class ImportJobDetailView(APIView):
    """GET /api/assets/upload/jobs/{id}/ — job status."""

    permission_classes = [IsAuthenticated, permission_required("asset.import")]

    def get(self, request, pk):
        try:
            job = AssetImportJob.objects.get(pk=pk)
        except AssetImportJob.DoesNotExist:
            return Response(
                {"detail": "Import job not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(AssetImportJobSerializer(job).data)


class ImportJobRowsView(ListAPIView):
    """GET /api/assets/upload/jobs/{id}/rows/ — job rows."""

    permission_classes = [IsAuthenticated, permission_required("asset.import")]
    serializer_class = AssetImportRowSerializer

    def get_queryset(self):
        job_id = self.kwargs["pk"]
        qs = AssetImportRow.objects.filter(job_id=job_id).order_by("row_number")
        row_status = self.request.query_params.get("status")
        if row_status:
            qs = qs.filter(status=row_status)
        return qs
