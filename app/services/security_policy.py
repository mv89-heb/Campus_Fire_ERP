"""Reusable security validation for request-level account operations."""
import re


MIN_PASSWORD_LENGTH = 12


def validate_password(password):
    """Raise ValueError when a new password is too weak."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f'Password must contain at least {MIN_PASSWORD_LENGTH} characters')
    if not re.search(r'[A-Z]', password):
        raise ValueError('Password must contain an uppercase letter')
    if not re.search(r'[a-z]', password):
        raise ValueError('Password must contain a lowercase letter')
    if not re.search(r'\d', password):
        raise ValueError('Password must contain a digit')
