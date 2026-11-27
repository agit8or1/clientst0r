"""
Backup-code page for django-two-factor-auth, with hashed storage.

Backup codes are stored hashed (accounts.otp_storage), so the library's
page — which lists the stored codes on every visit — would show hashes.
This subclass renders the freshly generated codes once, in the POST
response that created them, and afterwards only says how many are left.
Routed at the same path as two_factor:backup_tokens (config/urls.py) so
every link to that name lands here.
"""
from django.shortcuts import render
from django_otp.plugins.otp_static.models import StaticToken
from two_factor.views.core import BackupTokensView as _BackupTokensView


NUMBER_OF_CODES = 10


def generate_backup_codes(user, number=NUMBER_OF_CODES):
    """Replace the user's recovery codes with a fresh set and return the
    plain codes (the only moment they exist unhashed)."""
    device = user.staticdevice_set.get_or_create(name='backup')[0]
    device.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(number)]
    for code in codes:
        device.token_set.create(token=code)  # stored as a hash
    return codes


def render_fresh_backup_codes(request, codes, template_name='two_factor/core/backup_tokens.html',
                              context=None):
    """The backup-codes page showing `codes` once, never cached."""
    from django import forms
    device = request.user.staticdevice_set.get_or_create(name='backup')[0]
    ctx = {'form': forms.Form(), 'device': device, 'fresh_tokens': codes}
    ctx.update(context or {})
    response = render(request, template_name, ctx)
    response['Cache-Control'] = 'no-store, private'
    return response


class BackupTokensView(_BackupTokensView):
    template_name = 'two_factor/core/backup_tokens.html'
    number_of_tokens = NUMBER_OF_CODES

    def form_valid(self, form):
        codes = generate_backup_codes(self.request.user, self.number_of_tokens)
        context = self.get_context_data(form=form)
        context['fresh_tokens'] = codes
        response = render(self.request, self.template_name, context)
        response['Cache-Control'] = 'no-store, private'
        return response
