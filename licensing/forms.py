from django import forms

from assets.models import Asset, Contact

from .models import ExternalCustomerMap, LicenseAssignment, LicenseSubscription, SoftwareProduct


class SubscriptionForm(forms.ModelForm):
    product_vendor = forms.CharField(max_length=120, label='Vendor')
    product_name = forms.CharField(max_length=255, label='Product')
    product_sku = forms.CharField(max_length=120, required=False, label='Vendor SKU')
    license_type = forms.ChoiceField(choices=SoftwareProduct.TYPE_CHOICES, label='License type')

    class Meta:
        model = LicenseSubscription
        fields = ['vendor_subscription_id', 'quantity_purchased', 'unit_cost', 'unit_price', 'currency',
                  'billing_frequency', 'term_start', 'renewal_date', 'auto_renew', 'status',
                  'price_book_item_ref', 'notes']
        widgets = {'term_start': forms.DateInput(attrs={'type': 'date'}),
                   'renewal_date': forms.DateInput(attrs={'type': 'date'}),
                   'notes': forms.Textarea(attrs={'rows': 3})}

    ORDER = ['product_vendor', 'product_name', 'product_sku', 'license_type']

    def __init__(self, *args, organization, can_see_cost=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if not can_see_cost:
            # Never accepted, never echoed: an edit keeps the stored value.
            del self.fields['unit_cost']
        inst = self.instance
        if inst.pk:
            p = inst.product
            self.initial.update(product_vendor=p.vendor, product_name=p.name, product_sku=p.vendor_sku,
                                license_type=p.license_type)
        if inst.pk and inst.source != 'manual':
            # The vendor owns these; a sync would overwrite an edit.
            for name in ('vendor_subscription_id', 'quantity_purchased', 'status', 'product_vendor',
                         'product_name', 'product_sku', 'license_type'):
                if name in self.fields:
                    self.fields[name].disabled = True
        self.order_fields(self.ORDER + [f for f in self.fields if f not in self.ORDER])

    def clean_currency(self):
        return (self.cleaned_data.get('currency') or 'USD').upper()

    def clean(self):
        data = super().clean()
        vid = (data.get('vendor_subscription_id') or '').strip()
        source = self.instance.source if self.instance.pk else 'manual'
        if vid:
            dup = LicenseSubscription.objects.filter(organization=self.organization, source=source,
                                                     vendor_subscription_id=vid)
            if self.instance.pk:
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                self.add_error('vendor_subscription_id', 'Another subscription already has this id.')
        return data

    def save(self, commit=True):
        sub = super().save(commit=False)
        sub.organization = self.organization
        if not sub.pk:
            sub.source = 'manual'
        if sub.source == 'manual':
            d = self.cleaned_data
            sku = d.get('product_sku', '')
            if sku:
                product, _ = SoftwareProduct.objects.get_or_create(
                    vendor=d['product_vendor'], vendor_sku=sku,
                    defaults={'name': d['product_name'], 'license_type': d['license_type']})
            else:
                product, _ = SoftwareProduct.objects.get_or_create(
                    vendor=d['product_vendor'], name=d['product_name'], vendor_sku='',
                    defaults={'license_type': d['license_type']})
            sub.product = product
        if commit:
            sub.save()
        return sub


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = LicenseAssignment
        fields = ['assigned_to', 'contact', 'asset', 'assigned_at']
        widgets = {'assigned_at': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['contact'].queryset = Contact.objects.filter(organization=organization)
        self.fields['asset'].queryset = Asset.objects.filter(organization=organization)
        self.fields['assigned_to'].required = False

    def clean(self):
        data = super().clean()
        if not data.get('assigned_to'):
            if data.get('contact'):
                data['assigned_to'] = data['contact'].full_name
            elif data.get('asset'):
                data['assigned_to'] = data['asset'].name
            else:
                self.add_error('assigned_to', 'Say who or what holds the license.')
        return data


class CustomerMapForm(forms.ModelForm):
    class Meta:
        model = ExternalCustomerMap
        fields = ['source', 'external_id', 'external_name', 'organization']

    def __init__(self, *args, organizations, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['organization'].queryset = organizations
        self.fields['source'].choices = [c for c in LicenseSubscription.SOURCE_CHOICES if c[0] == 'pax8']
