import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)
    session_epoch = models.PositiveIntegerField(default=0)


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    ADMIN = "admin", "Administrator"
    ENGINEER = "engineer", "Test Engineer"
    OPERATOR = "operator", "Operator"
    VIEWER = "viewer", "Viewer"


class Membership(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    role = models.CharField(max_length=12, choices=Role.choices)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "user"], name="unique_membership")]


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    # M1 inventory records are unregistered, never reported as connected.
    source = models.CharField(max_length=12, choices=[("unknown", "Unknown"), ("simulated", "Simulated"), ("actual", "Actual")], default="unknown")
    capabilities = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} · {self.get_source_display()} · Not connected"


class TestDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    draft_header_bytes = models.PositiveIntegerField(default=0)


class DeviceGrant(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    device = models.ForeignKey(Device, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["membership", "device"], name="unique_device_grant")]


class TestGrant(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    test = models.ForeignKey(TestDefinition, on_delete=models.PROTECT)
    version = models.ForeignKey("TestVersion", on_delete=models.PROTECT, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["membership", "test"], condition=models.Q(version__isnull=True), name="unique_catalog_grant"),
            models.UniqueConstraint(fields=["membership", "version"], condition=models.Q(version__isnull=False), name="unique_version_grant"),
        ]


class Invitation(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    email = models.EmailField()
    role = models.CharField(max_length=12, choices=Role.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class AuditEvent(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, null=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # No update/delete interface is exposed. Database administrators remain trusted.


class LoginBucket(models.Model):
    key = models.CharField(max_length=64, unique=True)
    started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)


class TestVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    definition = models.ForeignKey(TestDefinition, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    manifest = models.JSONField()
    manifest_sha256 = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Published version snapshots are immutable; publish a new version.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.definition.name} v{self.number} ({self.pk})"

    class Meta:
        constraints = [models.UniqueConstraint(fields=["definition", "number"], name="unique_test_version_number")]


class TestApproval(models.Model):
    version = models.ForeignKey(TestVersion, on_delete=models.PROTECT, related_name="approvals")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approved_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version"], condition=models.Q(revoked_at__isnull=True), name="one_active_approval")]


class ServicePrincipal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=80)
    active = models.BooleanField(default=True)
    versions = models.ManyToManyField(TestVersion)
    devices = models.ManyToManyField(Device)


class ServiceToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    principal = models.ForeignKey(ServicePrincipal, on_delete=models.PROTECT)
    digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Artifact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    principal = models.ForeignKey(ServicePrincipal, on_delete=models.PROTECT, null=True)
    name = models.CharField(max_length=120)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} · {self.size} bytes · {str(self.pk)[:8]}"


class Batch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    principal = models.ForeignKey(ServicePrincipal, on_delete=models.PROTECT, null=True)
    requester_key = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=128)
    request_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["requester_key", "idempotency_key"], name="requester_idempotency")]


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="jobs")
    version = models.ForeignKey(TestVersion, on_delete=models.PROTECT)
    device = models.ForeignKey(Device, on_delete=models.PROTECT)
    expected = models.ForeignKey(Artifact, on_delete=models.PROTECT, related_name="expected_jobs")
    actual = models.ForeignKey(Artifact, on_delete=models.PROTECT, related_name="actual_jobs")
    parameters = models.JSONField()
    snapshot = models.JSONField()
    queue_deadline = models.DateTimeField()
    state = models.CharField(max_length=16, default="queued", choices=[("queued", "Queued")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["state", "created_at"], name="job_queue_idx")]


class Run(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(Job, on_delete=models.PROTECT, related_name="run")
    # No outcome/attempt/execution is created in M2A. These are queued logical runs only.


class Agent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    name = models.CharField(max_length=80)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    enabled = models.BooleanField(default=True)
    enrolled_at = models.DateTimeField(null=True)
    last_contact_at = models.DateTimeField(null=True)
    reported_platform = models.CharField(max_length=16, blank=True)
    reported_version = models.CharField(max_length=40, blank=True)
    devices = models.ManyToManyField(Device, through="AgentDevice")


class AgentDevice(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT)
    device = models.ForeignKey(Device, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["agent", "device"], name="unique_agent_device"),
            models.UniqueConstraint(fields=["device"], condition=models.Q(active=True), name="one_active_agent_per_device"),
        ]


class AgentEnrollment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)


class AgentCredential(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT)
    digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AgentHeartbeat(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT)
    heartbeat_id = models.UUIDField()
    body_sha256 = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["agent", "heartbeat_id"], name="unique_agent_heartbeat")]
        indexes = [models.Index(fields=["agent", "received_at"], name="agent_contact_idx")]
