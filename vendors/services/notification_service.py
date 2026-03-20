"""
Vendor notification emails.

These are portal-notification emails only — vendors must still log into
the portal to act.  Email links point to the authenticated portal and do
NOT bypass login.

Recipient rule:
  - VendorUserAssignment.is_active = True  (active org membership)
  - User.is_active = True                  (account not deactivated)
  - User has the 'vendor.respond' permission via an active role assignment
    (mirrors the portal access check in views_vendor.py)
"""
from django.conf import settings

from accounts.services.email_service import send_tracked_email


def _portal_request_url(vendor_request_id: str) -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:8081").rstrip("/")
    return f"{base}/vendor/requests/{vendor_request_id}"


def _active_recipient_emails(vendor_org) -> list[str]:
    """
    Return email addresses for vendor users who can actually use the portal.

    Filters to users that satisfy all three conditions:
      1. Active VendorUserAssignment for this org
      2. User.is_active = True
      3. Has the 'vendor.respond' permission through an active role assignment
    """
    return list(
        vendor_org.user_assignments
        .filter(
            is_active=True,
            user__is_active=True,
            user__role_assignments__is_active=True,
            user__role_assignments__role__role_permissions__permission__code="vendor.respond",
        )
        .values_list("user__email", flat=True)
        .distinct()
    )


def send_vendor_request_notification(vendor_request, *, sent_by=None) -> list[tuple]:
    """
    Send a 'new verification request' notification to all active vendor users.

    Called after a vendor request transitions from DRAFT → SENT.
    Should be triggered via transaction.on_commit() to avoid sending on
    a rolled-back write.

    Returns:
        List of (OutboundEmail, sent_ok) tuples — one per recipient.
    """
    vendor = vendor_request.vendor
    recipients = _active_recipient_emails(vendor)
    if not recipients:
        return []

    portal_url = _portal_request_url(str(vendor_request.pk))
    asset_count = vendor_request.request_assets.count()
    location_line = (
        f"\nSite / Location: {vendor_request.location_scope.name}"
        if vendor_request.location_scope_id
        else ""
    )
    sent_by_line = (
        f"\nAssigned by: {sent_by.get_full_name() or sent_by.email}"
        if sent_by
        else ""
    )

    subject = f"New Asset Verification Request – {vendor_request.reference_code}"
    body = (
        f"Hello,\n\n"
        f"A new asset verification request has been assigned to {vendor.name}.\n\n"
        f"Reference:  {vendor_request.reference_code}\n"
        f"Assets:     {asset_count}"
        f"{location_line}"
        f"{sent_by_line}\n\n"
        f"Please log in to the Vendor Portal to review and submit the request:\n"
        f"{portal_url}\n\n"
        f"Note: you must be logged in to access the request. "
        f"If you are not yet registered, contact your administrator.\n\n"
        f"— AssetVault"
    )

    results = []
    for email in recipients:
        record, ok = send_tracked_email(
            to_email=email,
            subject=subject,
            body=body,
            template_code="vendor_request_new",
            related_object_type="VendorVerificationRequest",
            related_object_id=str(vendor_request.pk),
        )
        results.append((record, ok))
    return results


def send_vendor_correction_notification(
    vendor_request,
    *,
    reviewed_by=None,
    approved_count: int = 0,
    correction_count: int = 0,
    note: str | None = None,
) -> list[tuple]:
    """
    Send a 'correction requested' notification to all active vendor users.

    Called after a vendor request transitions to CORRECTION_REQUESTED.
    Should be triggered via transaction.on_commit() to avoid sending on
    a rolled-back write.

    Returns:
        List of (OutboundEmail, sent_ok) tuples — one per recipient.
    """
    vendor = vendor_request.vendor
    recipients = _active_recipient_emails(vendor)
    if not recipients:
        return []

    portal_url = _portal_request_url(str(vendor_request.pk))
    reviewed_by_line = (
        f"\nReviewed by: {reviewed_by.get_full_name() or reviewed_by.email}"
        if reviewed_by
        else ""
    )
    note_line = f"\nAdmin note: {note}" if note else ""

    subject = f"Correction Requested – {vendor_request.reference_code}"
    body = (
        f"Hello,\n\n"
        f"Your verification request has been reviewed by {vendor.name}'s assigned administrator.\n\n"
        f"Reference:            {vendor_request.reference_code}\n"
        f"Assets approved:      {approved_count}\n"
        f"Assets requiring correction: {correction_count}"
        f"{reviewed_by_line}"
        f"{note_line}\n\n"
        f"Please log in to the Vendor Portal to review the items that need correction and resubmit:\n"
        f"{portal_url}\n\n"
        f"Only assets marked for correction need to be updated. Approved assets are locked.\n\n"
        f"— AssetVault"
    )

    results = []
    for email in recipients:
        record, ok = send_tracked_email(
            to_email=email,
            subject=subject,
            body=body,
            template_code="vendor_request_correction",
            related_object_type="VendorVerificationRequest",
            related_object_id=str(vendor_request.pk),
        )
        results.append((record, ok))
    return results
