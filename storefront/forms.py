from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Order, Review


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


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["rating", "title", "body"]
        widgets = {"rating": forms.Select(choices=[(i, f"{i} star{'s' if i > 1 else ''}") for i in range(1, 6)])}
