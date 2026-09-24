from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    BaseUserCreationForm,
    PasswordChangeForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Address, MarketingPreference, Order, OrderRequest, ProductQuestion, Review, SupportTicket, UserProfile

# Extra right padding so the show/hide password toggle button (added in the
# template) doesn't sit on top of the password text as the user types.
PASSWORD_WIDGET_ATTRS = {"class": "pr-12"}

# Mirrors AUTH_PASSWORD_VALIDATORS (settings.py) so a new password gets the
# same live client-side feedback wherever it's entered (signup, change
# password) as it gets from the server on submit.
NEW_PASSWORD_VALIDATE_RULE = "required minlength notnumeric notalpha special notcommon similarity"

# base.html's global `input{width:100%;padding:...}` rule is meant for text
# inputs; radios need the same "w-auto" override product_list.html already
# uses for its checkbox, or they render as oversized boxes.
RADIO_WIDGET_ATTRS = {"class": "ik-radio"}


def _validate_email_not_registered(email):
    email = email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError("An account already uses this email address. Please sign in instead.")
    return email


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"data-validate": "required"})
        self.fields["email"].widget.attrs.update({"data-validate": "required email"})
        self.fields["password1"].widget.attrs.update(
            {
                **PASSWORD_WIDGET_ATTRS,
                "data-validate": NEW_PASSWORD_VALIDATE_RULE,
                "data-similarity-to": "id_username id_email",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {**PASSWORD_WIDGET_ATTRS, "data-validate": "required match", "data-matches": "id_password1"}
        )

    def clean_email(self):
        return _validate_email_not_registered(self.cleaned_data["email"])

    def _post_clean(self):
        # BaseUserCreationForm._post_clean() builds self.instance (needed
        # before password validators can check it, e.g. for the similarity
        # check) and then runs AUTH_PASSWORD_VALIDATORS against "password2",
        # attaching any failure there. That puts complexity errors like "too
        # common" under "Confirm password" instead of "Password", which is
        # misleading when JS is off or misses a rule the server catches. Skip
        # straight to ModelForm's _post_clean (which builds self.instance)
        # and re-run the password check ourselves targeting password1.
        super(BaseUserCreationForm, self)._post_clean()
        self.validate_password_for_user(self.instance, "password1")


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"data-validate": "required"})
        self.fields["password"].widget.attrs.update(
            {**PASSWORD_WIDGET_ATTRS, "data-validate": "required"}
        )


class ChangePasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.update(
            {**PASSWORD_WIDGET_ATTRS, "data-validate": "required"}
        )
        self.fields["new_password1"].widget.attrs.update(
            {
                **PASSWORD_WIDGET_ATTRS,
                "data-validate": NEW_PASSWORD_VALIDATE_RULE,
                "data-similarity-to": "id_username id_email",
            }
        )
        self.fields["new_password2"].widget.attrs.update(
            {**PASSWORD_WIDGET_ATTRS, "data-validate": "required match", "data-matches": "id_new_password1"}
        )

    def clean(self):
        # SetPasswordForm.clean() runs AUTH_PASSWORD_VALIDATORS against
        # "new_password2", attaching any failure there ("Confirm new
        # password") instead of "New password". Same fix as
        # SignUpForm._post_clean(): reuse Django's own validation helpers,
        # just targeting new_password1, and skip SetPasswordForm.clean()
        # itself so it doesn't also run the check against new_password2.
        self.validate_passwords("new_password1", "new_password2")
        self.validate_password_for_user(self.user, "new_password1")
        return super(SetPasswordForm, self).clean()


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


class ChangePendingEmailForm(forms.Form):
    email = forms.EmailField(
        label="New email", widget=forms.EmailInput(attrs={"data-validate": "required email"})
    )

    def clean_email(self):
        return _validate_email_not_registered(self.cleaned_data["email"])


class CheckoutForm(forms.ModelForm):
    saved_address = forms.ModelChoiceField(
        queryset=Address.objects.none(), required=False, empty_label="Enter a new delivery address",
        widget=forms.RadioSelect(attrs={**RADIO_WIDGET_ATTRS}),
    )
    # payment_method is declared explicitly (rather than left to the
    # ModelForm machinery) so it doesn't get an unwanted blank "---------"
    # choice: it has no model-level default, so Django's default ModelForm
    # field generation includes a blank option for it (delivery_option has a
    # default, so it's unaffected and doesn't need this).
    payment_method = forms.ChoiceField(
        choices=Order.PaymentMethod.choices, widget=forms.RadioSelect(attrs={**RADIO_WIDGET_ATTRS})
    )
    coupon_code = forms.CharField(max_length=40, required=False, label="Coupon code")
    checkout_token = forms.UUIDField(widget=forms.HiddenInput)

    class Meta:
        model = Order
        fields = [
            "email", "full_name", "phone", "address_line1", "address_line2",
            "city", "state", "postal_code", "delivery_option", "payment_method",
        ]
        widgets = {
            "delivery_option": forms.RadioSelect(attrs={**RADIO_WIDGET_ATTRS}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.shipping_fields = ("full_name", "phone", "address_line1", "city", "state", "postal_code")
        for field in self.shipping_fields:
            self.fields[field].required = False
        self.fields["email"].widget.attrs.update({"data-validate": "required email"})
        for field in ("full_name", "phone", "address_line1", "city", "state", "postal_code"):
            self.fields[field].widget.attrs.update({"data-validate": "required"})
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
