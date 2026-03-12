from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.permissions import permission_required
from assets.models import Asset
from assets.services.asset_service import build_asset_qr_payload
from assets.views.bulk_upload_views import BulkUploadPreviewView, BulkUploadProcessView
from assets.views.dashboard_views import DashboardSummaryView
from assets.views.report_views import (
    AuditReportView,
    DiscrepancyReportView,
    ReconciliationReportView,
)
from submissions.views import (
    AdminApproveAssetView,
    AdminRejectAssetView,
    AdminSubmissionApproveView,
    AdminSubmissionCorrectionView,
    AdminSubmissionConvertView,
    AdminSubmissionDetailView,
    AdminSubmissionListView,
    AdminSubmissionRejectView,
    AdminSubmissionReviewView,
    EmployeeAddMissingAssetView,
    EmployeeSubmitVerificationView,
    EmployeeVerifyAssetsView,
    ReconciliationSubmitView,
    SubmissionDetailView,
    SubmissionListCreateView,
    ThirdPartyAddAssetView,
    ThirdPartyVerifyView,
)


# ---------------------------------------------------------------------------
# Inline compatibility views (kept small — most logic lives in app views)
# ---------------------------------------------------------------------------


class AssetUploadAliasView(BulkUploadPreviewView):
    """POST /api/assets/upload — routes to preview or process based on job_id."""

    def post(self, request):
        if request.data.get("job_id"):
            return BulkUploadProcessView.as_view()(request._request)
        return super().post(request)


class AssetGenerateQRView(APIView):
    """GET /api/assets/generate-qr?asset_id=...&id=..."""

    permission_classes = [IsAuthenticated, permission_required("asset.view")]

    def get(self, request):
        import uuid as _uuid

        from access.helpers import location_in_scope

        asset_id_str = request.query_params.get(
            "asset_id", request.query_params.get("id")
        )
        if not asset_id_str:
            return Response(
                {"detail": "asset_id or id query parameter is required."},
                status=400,
            )

        try:
            asset = Asset.objects.select_related(
                "category", "current_location"
            ).get(asset_id=asset_id_str)
        except Asset.DoesNotExist:
            try:
                pk = _uuid.UUID(str(asset_id_str))
            except (ValueError, AttributeError):
                return Response(
                    {"detail": "Invalid id format — expected a UUID."},
                    status=400,
                )
            try:
                asset = Asset.objects.select_related(
                    "category", "current_location"
                ).get(pk=pk)
            except Asset.DoesNotExist:
                return Response({"detail": "Asset not found."}, status=404)

        if not location_in_scope(asset.current_location_id, request.user):
            return Response({"detail": "Asset not found."}, status=404)

        return Response(build_asset_qr_payload(asset))


class SendVerificationRequestAliasView(APIView):
    """POST /api/admin/send-verification-request — single-asset compat alias."""

    permission_classes = [IsAuthenticated, permission_required("verification.request")]

    def post(self, request):
        from verification.views import QuickSendVerificationView
        return QuickSendVerificationView.as_view()(request._request)


# ---------------------------------------------------------------------------
# URL patterns
# ---------------------------------------------------------------------------

urlpatterns = [
    path("admin/", admin.site.urls),

    # ── Core API routes ────────────────────────────────────────────────
    path("api/auth/", include("accounts.urls")),
    path("api/assets/", include("assets.urls")),
    path("api/locations/", include("locations.urls")),
    path("api/verification/", include("verification.urls")),
    path("api/submissions/", include("submissions.urls")),

    # ── Dashboard & reports ────────────────────────────────────────────
    path("api/dashboard/summary", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("api/reports/reconciliation", ReconciliationReportView.as_view(), name="report-reconciliation"),
    path("api/reports/discrepancy", DiscrepancyReportView.as_view(), name="report-discrepancy"),
    path("api/reports/audit", AuditReportView.as_view(), name="report-audit"),

    # ── Asset compatibility aliases ────────────────────────────────────
    path("api/assets/upload", AssetUploadAliasView.as_view(), name="asset-upload-alias"),
    path("api/assets/generate-qr", AssetGenerateQRView.as_view(), name="asset-generate-qr"),

    # ── /api/third-party/* ─────────────────────────────────────────────
    path("api/third-party/submissions/", SubmissionListCreateView.as_view(), name="tp-submissions"),
    path("api/third-party/submissions/<uuid:pk>/", SubmissionDetailView.as_view(), name="tp-submission-detail"),
    path("api/third-party/verify", ThirdPartyVerifyView.as_view(), name="tp-verify"),
    path("api/third-party/add-asset", ThirdPartyAddAssetView.as_view(), name="tp-add-asset"),

    # ── /api/admin/* ───────────────────────────────────────────────────
    path("api/admin/submissions/", AdminSubmissionListView.as_view(), name="admin-submissions"),
    path("api/admin/submissions/<uuid:pk>/", AdminSubmissionDetailView.as_view(), name="admin-submission-detail"),
    path("api/admin/submissions/<uuid:pk>/review/", AdminSubmissionReviewView.as_view(), name="admin-submission-review"),
    path("api/admin/submissions/<uuid:pk>/approve/", AdminSubmissionApproveView.as_view(), name="admin-submission-approve"),
    path("api/admin/submissions/<uuid:pk>/reject/", AdminSubmissionRejectView.as_view(), name="admin-submission-reject"),
    path("api/admin/submissions/<uuid:pk>/correction/", AdminSubmissionCorrectionView.as_view(), name="admin-submission-correction"),
    path("api/admin/submissions/<uuid:pk>/convert-to-asset/", AdminSubmissionConvertView.as_view(), name="admin-submission-convert"),
    path("api/admin/approve-asset", AdminApproveAssetView.as_view(), name="admin-approve-asset"),
    path("api/admin/reject-asset", AdminRejectAssetView.as_view(), name="admin-reject-asset"),
    path("api/admin/send-verification-request", SendVerificationRequestAliasView.as_view(), name="admin-send-vr"),

    # ── /api/employee/* ────────────────────────────────────────────────
    path("api/employee/verify-assets", EmployeeVerifyAssetsView.as_view(), name="employee-verify-assets"),
    path("api/employee/add-missing-asset", EmployeeAddMissingAssetView.as_view(), name="employee-add-missing"),
    path("api/employee/submit-verification", EmployeeSubmitVerificationView.as_view(), name="employee-submit-verification"),

    # ── /api/reconciliation/* ──────────────────────────────────────────
    path("api/reconciliation/report", ReconciliationReportView.as_view(), name="reconciliation-report-alias"),
    path("api/reconciliation/submit", ReconciliationSubmitView.as_view(), name="reconciliation-submit"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
