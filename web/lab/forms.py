from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from .models import Role


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "username"}))
    error_messages = {"invalid_login": "Unable to sign in with those credentials.", "inactive": "Unable to sign in with those credentials."}

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class InviteForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=Role.choices)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This account already exists. Use the local membership command to add an existing account.")
        return email


class AcceptForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, *args, email="", **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email

    def clean(self):
        data = super().clean()
        if data.get("password") != data.get("confirm_password"):
            raise forms.ValidationError("Passwords must match.")
        if data.get("password"):
            password_validation.validate_password(data["password"], get_user_model()(username=self.email, email=self.email))
        return data


class MemberForm(forms.Form):
    role = forms.ChoiceField(choices=Role.choices)
    active = forms.BooleanField(required=False)


class GrantForm(forms.Form):
    kind = forms.ChoiceField(choices=[("device", "Device"), ("test", "Test")])
    record = forms.UUIDField()
    granted = forms.BooleanField(required=False)


class QueueForm(forms.Form):
    version = forms.ModelChoiceField(queryset=None, label="Approved test version")
    device = forms.ModelChoiceField(queryset=None)
    expected = forms.ModelChoiceField(queryset=None, label="Expected input")
    actual = forms.ModelChoiceField(queryset=None, label="Actual input")
    header_bytes = forms.IntegerField(min_value=0, max_value=4096, help_text="Must match the approved version's reference-header policy.")
    idempotency_key = forms.RegexField(regex=r"^[A-Za-z0-9._:-]{1,128}$", max_length=128, help_text="Reuse this key only to retry the identical submission.")
    queue_seconds = forms.IntegerField(min_value=60, max_value=86400, initial=3600)

    def __init__(self, *args, user, project, **kwargs):
        from .models import Artifact, Device, Membership, TestVersion
        from django.db.models import Q
        super().__init__(*args, **kwargs)
        member = Membership.objects.filter(user=user, project=project, active=True).first()
        self.fields["version"].queryset = TestVersion.objects.filter(definition__project=project, testgrant__membership=member, approvals__revoked_at=None, approvals__isnull=False).distinct()
        self.fields["device"].queryset = Device.objects.filter(project=project, devicegrant__membership=member).distinct()
        inputs = Artifact.objects.filter(project=project)
        if not user.is_superuser and (member is None or member.role != Role.ADMIN):
            inputs = inputs.filter(owner=user)
        for name in ["expected", "actual"]:
            self.fields[name].queryset = inputs.order_by("created_at")


class InputForm(forms.Form):
    file = forms.FileField(label="CAN fixture input (ASCII text, at most 1 MiB)")
    sha256 = forms.RegexField(regex=r"^[0-9a-f]{64}$", label="Expected SHA-256")

    def clean_file(self):
        from django.conf import settings
        upload = self.cleaned_data["file"]
        if not 1 <= upload.size <= settings.MAX_INPUT_BYTES:
            raise forms.ValidationError("Input must contain 1 byte to 1 MiB.")
        return upload


class DraftForm(forms.Form):
    name = forms.CharField(max_length=120)
    header_bytes = forms.IntegerField(min_value=0, max_value=4096, initial=0)
    definition_id = forms.UUIDField(required=False, label="Existing draft ID (blank creates a new draft)")
