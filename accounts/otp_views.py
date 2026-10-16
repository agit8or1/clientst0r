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


class BackupTokensView(_BackupTokensView):
    template_name = 'two_factor/core/backup_tokens.html'

    def form_valid(self, form):
        device = self.get_device()
        device.token_set.all().delete()
        codes = [StaticToken.random_token() for _ in range(self.number_of_tokens)]
        for code in codes:
            device.token_set.create(token=code)  # stored as a hash
        context = self.get_context_data(form=form)
        context['fresh_tokens'] = codes
        response = render(self.request, self.template_name, context)
        response['Cache-Control'] = 'no-store, private'
        return response
