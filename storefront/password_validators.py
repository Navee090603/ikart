import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

SPECIAL_CHARACTER_PATTERN = re.compile(r"[^A-Za-z0-9]")


class NotAllAlphabeticValidator:
    """Rejects passwords made up of letters only (mirrors Django's own
    NumericPasswordValidator, which rejects digits-only passwords)."""

    def validate(self, password, user=None):
        if password.isalpha():
            raise ValidationError(
                _("Your password can't contain only letters."),
                code="password_all_alphabetic",
            )

    def get_help_text(self):
        return _("Your password can't contain only letters.")


class SpecialCharacterValidator:
    def validate(self, password, user=None):
        if not SPECIAL_CHARACTER_PATTERN.search(password):
            raise ValidationError(
                _("Your password must contain at least one special character."),
                code="password_no_special_character",
            )

    def get_help_text(self):
        return _("Your password must contain at least one special character.")
