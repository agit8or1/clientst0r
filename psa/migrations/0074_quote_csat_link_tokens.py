"""Customer link tokens at rest (v3.17.611).

Quote.customer_token: plaintext -> encrypted (enc2$) + customer_token_hash.
    The sign link is embedded in the quote PDF and email each time staff
    view, download or re-send a quote, so it stays re-displayable; the
    public sign page looks quotes up by the hash. Existing links keep working.

TicketCSATSurvey.token -> token_hash (HMAC only). The survey link is emailed
    once, when the survey is created, and never displayed again. Existing
    tokens are hashed in place, so emailed links keep working. Irreversible
    for the token values (reverse is a no-op).
"""
import vault.secret_fields
from django.db import migrations, models
from vault.secret_fields import hash_and_seal_token_operation, hash_token_column_operation


class Migration(migrations.Migration):

    dependencies = [
        ('psa', '0073_seal_email_password_push_secret'),
    ]

    operations = [
        migrations.AddField(
            model_name='quote',
            name='customer_token_hash',
            field=models.CharField(blank=True, db_index=True, editable=False, help_text='HMAC-SHA256 of customer_token, for lookups', max_length=64),
        ),
        migrations.AlterField(
            model_name='quote',
            name='customer_token',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='Opaque token for the customer-facing sign-and-accept URL (encrypted at rest)'),
        ),
        hash_and_seal_token_operation('psa', 'Quote', 'customer_token', 'customer_token_hash',
                                      'psa.quote.sign'),
        migrations.RenameField(
            model_name='ticketcsatsurvey',
            old_name='token',
            new_name='token_hash',
        ),
        hash_token_column_operation('psa', 'TicketCSATSurvey', 'token_hash', 'psa.csat'),
    ]
