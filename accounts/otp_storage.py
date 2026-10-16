"""
2FA secrets at rest: encrypt TOTP seeds, hash static backup codes.

django-otp stores ``TOTPDevice.key`` (the TOTP seed) and
``StaticToken.token`` (backup codes) as plain varchar columns. Every 2FA
path in this app — django-two-factor-auth's login wizard, setup wizard, QR
view and backup-token page, our own profile enrolment
(accounts.views.two_factor_setup), the mobile MFA step
(api_mobile.auth_utils.verify_totp_code) and the admin — goes through those
two model fields. Swapping the *class* of the two field instances for
subclasses that encrypt/hash in get_prep_value (and decrypt in
from_db_value) therefore covers every reader and writer without forking the
library or replacing its models:

* TOTPDevice.key  -> vault.secret_fields.EncryptedHexKeyField. Attribute is
  still the hex seed (``bin_key``, ``config_url`` and verify_token work
  unchanged); the column holds ``enc2h$...``.
* StaticToken.token -> vault.secret_fields.HashedStaticTokenField. The
  column (and attribute, once read back) holds ``h$<hash>``;
  ``StaticDevice.verify_token``'s ``token_set.filter(token=code)`` hashes the
  submitted code the same way, so verification is unchanged. The codes can
  only be shown when generated (accounts.otp_views.BackupTokensView).

A custom device model was the alternative. It would mean replacing the
device classes two_factor hard-codes (TOTPDevice in its setup wizard and
QR view, StaticDevice/StaticToken in its login wizard, backup page and
profile), i.e. forking most of its views — far more surface than this.

Existing rows are converted by accounts migration 0036.
"""
import logging

from django.db import models

logger = logging.getLogger('accounts')

_installed = False


def _swap(model, field_name, new_class, expected_max_length):
    field = model._meta.get_field(field_name)
    if isinstance(field, new_class):
        return field
    # Refuse to guess if a django-otp upgrade changed the column: a silent
    # mismatch here would mean secrets quietly stop being protected, or
    # stop being readable.
    if type(field) is not models.CharField or field.max_length != expected_max_length:
        raise RuntimeError(
            f'{model.__name__}.{field_name} is no longer a CharField(max_length='
            f'{expected_max_length}); review accounts/otp_storage.py before upgrading '
            f'django-otp.')
    field.__class__ = new_class
    return field


def install():
    """Wire encryption/hashing onto django-otp's fields. Idempotent."""
    global _installed
    if _installed:
        return
    from django_otp.plugins.otp_static.models import StaticToken
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from vault.secret_fields import EncryptedHexKeyField, HashedStaticTokenField

    _swap(TOTPDevice, 'key', EncryptedHexKeyField, 80)
    _swap(StaticToken, 'token', HashedStaticTokenField, 16)
    _installed = True
