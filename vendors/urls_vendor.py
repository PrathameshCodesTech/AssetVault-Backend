from django.urls import path

from vendors.views_vendor import (
    VendorGlobalScanView,
    VendorRequestAssetPhotoUploadView,
    VendorRequestAssetUpdateView,
    VendorRequestDetailView,
    VendorRequestListView,
    VendorRequestScanView,
    VendorRequestSubmitView,
)

urlpatterns = [
    path("requests/", VendorRequestListView.as_view()),
    # Global scan must come BEFORE <uuid:pk> routes
    path("requests/scan/", VendorGlobalScanView.as_view()),
    path("requests/<uuid:pk>/", VendorRequestDetailView.as_view()),
    path("requests/<uuid:pk>/submit/", VendorRequestSubmitView.as_view()),
    path("requests/<uuid:pk>/scan/", VendorRequestScanView.as_view()),
    path("requests/<uuid:pk>/assets/<uuid:asset_pk>/", VendorRequestAssetUpdateView.as_view()),
    path("requests/<uuid:pk>/assets/<uuid:asset_pk>/photos/", VendorRequestAssetPhotoUploadView.as_view()),
]
