from django.urls import path

from vendors.views_admin import (
    AdminVendorDetailView,
    AdminVendorListCreateView,
    AdminVendorRequestApproveView,
    AdminVendorRequestAssetDecisionView,
    AdminVendorRequestAssetRemoveView,
    AdminVendorRequestCancelView,
    AdminVendorRequestCorrectionView,
    AdminVendorRequestDetailView,
    AdminVendorRequestListCreateView,
    AdminVendorRequestSendView,
    AdminVendorUserListCreateView,
    AdminVendorUserRemoveView,
)

urlpatterns = [
    # Vendor organization management (superadmin)
    path("vendors/", AdminVendorListCreateView.as_view()),
    path("vendors/<uuid:pk>/", AdminVendorDetailView.as_view()),
    path("vendors/<uuid:pk>/users/", AdminVendorUserListCreateView.as_view()),
    path("vendors/<uuid:pk>/users/<uuid:assignment_id>/", AdminVendorUserRemoveView.as_view()),

    # Vendor verification request management (admin)
    path("vendor-requests/", AdminVendorRequestListCreateView.as_view()),
    path("vendor-requests/<uuid:pk>/", AdminVendorRequestDetailView.as_view()),
    path("vendor-requests/<uuid:pk>/send/", AdminVendorRequestSendView.as_view()),
    path("vendor-requests/<uuid:pk>/cancel/", AdminVendorRequestCancelView.as_view()),
    path("vendor-requests/<uuid:pk>/approve/", AdminVendorRequestApproveView.as_view()),
    path("vendor-requests/<uuid:pk>/correction/", AdminVendorRequestCorrectionView.as_view()),
    path("vendor-requests/<uuid:pk>/assets/<uuid:asset_pk>/", AdminVendorRequestAssetRemoveView.as_view()),
    path("vendor-requests/<uuid:pk>/assets/<uuid:asset_pk>/decision/", AdminVendorRequestAssetDecisionView.as_view()),
]
