"""
Reusable email sending helper that actually dispatches email and
creates an OutboundEmail audit record in a single call.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from accounts.models import OutboundEmail

logger = logging.getLogger(__name__)


def send_tracked_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    template_code: str = "",
    related_object_type: str = "",
    related_object_id: str = "",
    from_email: str | None = None,
) -> tuple[OutboundEmail, bool]:
    """
    Send an email and persist an OutboundEmail audit record.

    Returns:
        (OutboundEmail, sent_ok) — the log row and whether sending succeeded.
    """
    sender = from_email or settings.DEFAULT_FROM_EMAIL

    record = OutboundEmail(
        to_email=to_email,
        subject=subject,
        body=body,
        template_code=template_code or "",
        related_object_type=related_object_type or "",
        related_object_id=related_object_id or "",
        status=OutboundEmail.Status.PENDING,
    )

    try:
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=sender,
            to=[to_email],
        )
        msg.send(fail_silently=False)

        record.status = OutboundEmail.Status.SENT
        record.sent_at = timezone.now()
        record.save()
        return record, True

    except Exception as exc:
        logger.exception("Failed to send email to %s: %s", to_email, exc)
        record.status = OutboundEmail.Status.FAILED
        record.failure_reason = str(exc)[:2000]
        record.save()
        return record, False
