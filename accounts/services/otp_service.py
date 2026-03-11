"""
OTP lifecycle service.

Responsibilities:
- create_otp_challenge: hash a new OTP, store OtpChallenge, return the raw code to the caller
- verify_otp: validate code hash, check expiry/block/consumed state, increment attempt count
- mark_otp_consumed: mark consumed_at timestamp
- check_resend_throttle: raise if send_count has exceeded limit within window

No email sending here — the caller (view/task) is responsible for delivering the raw code.

Security note — hashing:
    A six-digit OTP has only 1 000 000 possible values.  Plain SHA-256 is fast
    and keyless, making offline brute-force trivial if the DB is exposed.
    We use HMAC-SHA256 keyed on Django's SECRET_KEY so that knowledge of the
    stored hash alone is not enough to reverse the code — the attacker also
    needs the SECRET_KEY.  Rotate SECRET_KEY to invalidate all outstanding OTPs.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from accounts.models import OtpChallenge, OutboundEmail

OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 10
MAX_RESEND_PER_HOUR = 3


def _hash_code(raw_code: str) -> str:
    """Return HMAC-SHA256(SECRET_KEY, raw_code) as a hex digest.

    Using the SECRET_KEY as a pepper makes offline brute-force impractical
    even when the full DB contents are known to an attacker.
    """
    return hmac.new(
        settings.SECRET_KEY.encode(),
        raw_code.encode(),
        hashlib.sha256,
    ).hexdigest()


def generate_raw_otp() -> str:
    return str(secrets.randbelow(10 ** OTP_LENGTH)).zfill(OTP_LENGTH)


def create_otp_challenge(
    email: str,
    purpose: str,
    *,
    user=None,
    related_object_type: str | None = None,
    related_object_id: str | None = None,
    expiry_minutes: int = OTP_EXPIRY_MINUTES,
) -> tuple["OtpChallenge", str]:
    """
    Create and store a new OTP challenge.

    Returns (challenge_instance, raw_code). The raw_code must be delivered to the
    user by the caller — it is not stored and cannot be recovered later.
    """
    raw_code = generate_raw_otp()
    challenge = OtpChallenge.objects.create(
        email=email,
        user=user,
        purpose=purpose,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        code_hash=_hash_code(raw_code),
        expires_at=timezone.now() + timedelta(minutes=expiry_minutes),
        send_count=1,
        last_sent_at=timezone.now(),
    )
    return challenge, raw_code


def verify_otp(challenge: "OtpChallenge", raw_code: str) -> bool:
    """
    Validate raw_code against the stored hash.

    Returns True on success. Raises ValueError with a user-facing message on failure.
    Does NOT consume the challenge — call mark_otp_consumed() after successful verification.
    """
    if challenge.is_consumed:
        raise ValueError("This OTP has already been used.")
    if challenge.is_expired:
        raise ValueError("This OTP has expired.")
    if challenge.is_blocked:
        raise ValueError("Too many failed attempts. Please request a new OTP.")

    challenge.attempt_count += 1
    is_valid = hmac.compare_digest(challenge.code_hash, _hash_code(raw_code))

    if not is_valid:
        if challenge.attempt_count >= challenge.max_attempts:
            challenge.blocked_until = timezone.now() + timedelta(minutes=30)
        challenge.save(update_fields=["attempt_count", "blocked_until"])
        raise ValueError("Invalid OTP.")

    challenge.save(update_fields=["attempt_count"])
    return True


def mark_otp_consumed(challenge: "OtpChallenge") -> None:
    """Mark the challenge as consumed. Call immediately after successful verification."""
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])


_PURPOSE_TEMPLATE_MAP = {
    OtpChallenge.Purpose.LOGIN: "login_otp",
    OtpChallenge.Purpose.EMPLOYEE_VERIFICATION: "verification_otp",
}


def check_resend_throttle(
    email: str, purpose: str, max_per_hour: int = MAX_RESEND_PER_HOUR
) -> None:
    """
    Raise ValueError if too many OTPs have been *successfully delivered* to
    this email+purpose in the last hour.

    Counts OutboundEmail rows with status=sent so that failed SMTP attempts
    do not consume the resend quota.
    """
    window_start = timezone.now() - timedelta(hours=1)
    template_code = _PURPOSE_TEMPLATE_MAP.get(purpose)

    if template_code:
        count = OutboundEmail.objects.filter(
            to_email=email,
            template_code=template_code,
            status=OutboundEmail.Status.SENT,
            created_at__gte=window_start,
        ).count()
    else:
        count = OtpChallenge.objects.filter(
            email=email,
            purpose=purpose,
            created_at__gte=window_start,
        ).count()

    if count >= max_per_hour:
        raise ValueError(
            "Too many OTP requests. Please wait before requesting again."
        )
