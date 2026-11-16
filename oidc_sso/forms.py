from urllib.parse import urlsplit

from django import forms

from .models import ALLOWED_ALGORITHMS, OIDCProvider

PIN_FIELDS = ('issuer', 'client_id', 'org_claim', 'msp_org_alias', 'msp_org_id')


class ProviderForm(forms.ModelForm):
    class Meta:
        model = OIDCProvider
        fields = ['name', 'slug', 'enabled', 'issuer', 'client_id', 'client_auth_method', 'client_secret',
                  'scopes', 'allowed_algorithms', 'use_userinfo', 'org_claim', 'msp_org_alias', 'msp_org_id',
                  'roles_claim', 'jit_provisioning', 'require_email_verified', 'accept_idp_mfa',
                  'mfa_acr_values', 'mfa_amr_values', 'login_acr_values', 'stepup_acr_values',
                  'allow_private_network', 'ca_bundle_pem', 'rp_logout']
        widgets = {'ca_bundle_pem': forms.Textarea(attrs={'rows': 4, 'class': 'font-monospace'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')
        self.fields['client_secret'].required = False
        self.fields['client_secret'].help_text = ('Only for client_secret_basic. Leave empty to keep the stored '
                                                  'secret; it is never shown again.')

    def clean_issuer(self):
        issuer = (self.cleaned_data.get('issuer') or '').strip()
        parts = urlsplit(issuer)
        if parts.query or parts.fragment or parts.username or parts.password:
            raise forms.ValidationError('The issuer has no query, fragment or credentials.')
        if parts.scheme not in ('https', 'http'):
            raise forms.ValidationError('Use an https:// issuer.')
        return issuer

    def clean_allowed_algorithms(self):
        algs = [a for a in (self.cleaned_data.get('allowed_algorithms') or '').replace(',', ' ').split() if a]
        bad = [a for a in algs if a not in ALLOWED_ALGORITHMS]
        if bad or not algs:
            raise forms.ValidationError(f'Choose from {" ".join(ALLOWED_ALGORITHMS)} ("none" and HS* are never '
                                        'accepted).')
        return ' '.join(algs)

    def clean_scopes(self):
        scopes = (self.cleaned_data.get('scopes') or '').split()
        if 'openid' not in scopes:
            scopes.insert(0, 'openid')
        return ' '.join(scopes)

    def clean_ca_bundle_pem(self):
        pem = (self.cleaned_data.get('ca_bundle_pem') or '').strip()
        if not pem:
            return ''
        from cryptography import x509
        try:
            certs = x509.load_pem_x509_certificates(pem.encode())
        except ValueError:
            raise forms.ValidationError('Not a PEM certificate bundle.')
        if not certs:
            raise forms.ValidationError('Not a PEM certificate bundle.')
        return pem

    def clean(self):
        data = super().clean()
        issuer = data.get('issuer') or ''
        if issuer.startswith('http://') and not data.get('allow_private_network'):
            self.add_error('issuer', 'http:// is only allowed with "private network" on (testing).')
        if data.get('enabled'):
            if data.get('org_claim') and not (data.get('msp_org_alias') or '').strip():
                self.add_error('msp_org_alias', 'Pin the MSP organization before enabling sign-in.')
            method = data.get('client_auth_method')
            if method == OIDCProvider.AUTH_CLIENT_SECRET_BASIC and not (
                    data.get('client_secret') or (self.instance and self.instance.client_secret)):
                self.add_error('client_secret', 'Enter the client secret.')
            if method == OIDCProvider.AUTH_PRIVATE_KEY_JWT and not (self.instance and self.instance.key_id):
                self.add_error('client_auth_method', 'Generate a key pair first.')
        return data
