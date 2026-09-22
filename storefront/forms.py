from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Address, MarketingPreference, Order, OrderRequest, ProductQuestion, Review, SupportTicket, UserProfile


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account already uses this email address. Please sign in instead.")
        return email


class OTPVerificationForm(forms.Form):
    code = forms.CharField(
        label="Verification code", min_length=6, max_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "placeholder": "000000"}),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit() or len(code) != 6:
            raise ValidationError("Enter the six-digit code from your email.")
        return code


class CheckoutForm(forms.ModelForm):
    saved_address = forms.ModelChoiceField(queryset=Address.objects.none(), required=False, empty_label="Enter a new delivery address")
    coupon_code = forms.CharField(max_length=40, required=False, label="Coupon code")
    checkout_token = forms.UUIDField(widget=forms.HiddenInput)

    class Meta:
        model = Order
        fields = [
            "email", "full_name", "phone", "address_line1", "address_line2",
            "city", "state", "postal_code", "delivery_option", "payment_method",
        ]
        widgets = {
            "delivery_option": forms.RadioSelect,
            "payment_method": forms.RadioSelect,
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.shipping_fields = ("full_name", "phone", "address_line1", "city", "state", "postal_code")
        for field in self.shipping_fields:
            self.fields[field].required = False
        if user and user.is_authenticated:
            addresses = user.addresses.order_by("-is_default", "-id")
            self.fields["saved_address"].queryset = addresses
            default_address = addresses.filter(is_default=True).first() or addresses.first()
            if default_address and not self.is_bound:
                self.initial.update({
                    "saved_address": default_address, "full_name": default_address.full_name,
                    "phone": default_address.phone, "address_line1": default_address.line1,
                    "address_line2": default_address.line2, "city": default_address.city,
                    "state": default_address.state, "postal_code": default_address.postal_code,
                })
        else:
            self.fields.pop("saved_address")

    def clean(self):
        cleaned = super().clean()
        address = cleaned.get("saved_address")
        if address:
            cleaned.update({
                "full_name": address.full_name, "phone": address.phone, "address_line1": address.line1,
                "address_line2": address.line2, "city": address.city, "state": address.state,
                "postal_code": address.postal_code,
            })
        else:
            for field in self.shipping_fields:
                if not cleaned.get(field):
                    self.add_error(field, "This field is required.")
        return cleaned


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ("full_name", "phone", "line1", "line2", "city", "state", "postal_code", "is_default")


class ProductQuestionForm(forms.ModelForm):
    class Meta:
        model = ProductQuestion
        fields = ("question",)
        widgets = {"question": forms.Textarea(attrs={"rows": 3, "placeholder": "Ask a question about this product"})}

    def clean_question(self):
        question = " ".join(self.cleaned_data["question"].split())
        if len(question) < 10:
            raise ValidationError("Please enter at least 10 characters.")
        return question


class OrderRequestForm(forms.ModelForm):
    class Meta:
        model = OrderRequest
        fields = ("reason", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3, "placeholder": "Add any helpful details (optional)"})}


class SupportTicketForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ("order", "category", "subject", "message")
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            self.fields["order"].queryset = user.orders.all()


class ProductCSVUploadForm(forms.Form):
    csv_file = forms.FileField(help_text="CSV columns: name, category, price, stock, description. Optional: brand, short_description, compare_at_price, low_stock_threshold, is_featured, is_active.")


class MarketingPreferenceForm(forms.ModelForm):
    class Meta:
        model = MarketingPreference
        fields = ("email_promotions", "sms_promotions")


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("phone",)
        widgets = {"phone": forms.TextInput(attrs={"placeholder": "e.g. 9876543210"})}


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["rating", "title", "body"]
        widgets = {"rating": forms.Select(choices=[(i, f"{i} star{'s' if i > 1 else ''}") for i in range(1, 6)])}


class CategoryCSVUploadForm(forms.Form):
    csv_file = forms.FileField()
