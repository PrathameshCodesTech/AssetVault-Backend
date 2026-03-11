from django.urls import path

from assets.views.asset_views import (
    AssetDetailView,
    AssetHistoryView,
    AssetAssignView,
    AssetListCreateView,
    AssetLookupsView,
    AssetMoveView,
    AssetQRView,
    AssetScanView,
)
from assets.views.bulk_upload_views import (
    BulkUploadPreviewView,
    BulkUploadProcessView,
    ImportJobDetailView,
    ImportJobRowsView,
)

app_name = "assets"

urlpatterns = [
    # Main asset CRUD
    path("", AssetListCreateView.as_view(), name="list-create"),
    path("<uuid:pk>/", AssetDetailView.as_view(), name="detail"),
    path("<uuid:pk>/history/", AssetHistoryView.as_view(), name="history"),
    path("<uuid:pk>/assign/", AssetAssignView.as_view(), name="assign"),
    path("<uuid:pk>/move/", AssetMoveView.as_view(), name="move"),
    path("<uuid:pk>/qr/", AssetQRView.as_view(), name="qr"),
    path("scan/<uuid:qr_uid>/", AssetScanView.as_view(), name="scan"),
    path("lookups/", AssetLookupsView.as_view(), name="lookups"),
    # Bulk upload
    path("upload/preview/", BulkUploadPreviewView.as_view(), name="upload-preview"),
    path("upload/process/", BulkUploadProcessView.as_view(), name="upload-process"),
    path("upload/jobs/<uuid:pk>/", ImportJobDetailView.as_view(), name="upload-job-detail"),
    path("upload/jobs/<uuid:pk>/rows/", ImportJobRowsView.as_view(), name="upload-job-rows"),
]
