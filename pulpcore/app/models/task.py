"""
Django models related to the Tasking system
"""
import logging
import traceback
import os
from datetime import timedelta
from gettext import gettext as _

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, models
from django.utils import timezone

from pulpcore.app.models import (
    AutoAddObjPermsMixin,
    AutoDeleteObjPermsMixin,
    BaseModel,
    GenericRelationModel,
)
from pulpcore.constants import TASK_CHOICES, TASK_FINAL_STATES, TASK_STATES
from pulpcore.exceptions import AdvisoryLockError, exception_to_dict
from pulpcore.tasking.constants import TASKING_CONSTANTS


_logger = logging.getLogger(__name__)


class WorkerManager(models.Manager):
    def online_workers(self):
        """
        Returns a queryset of workers meeting the criteria to be considered 'online'

        To be considered 'online', a worker must have a recent heartbeat timestamp. "Recent" is
        defined here as "within the pulp process timeout interval".

        Returns:
            :class:`django.db.models.query.QuerySet`:  A query set of the Worker objects which
                are considered by Pulp to be 'online'.
        """
        now = timezone.now()
        age_threshold = now - timedelta(seconds=settings.WORKER_TTL)

        return self.filter(last_heartbeat__gte=age_threshold)

    def missing_workers(self, age=timedelta(seconds=settings.WORKER_TTL)):
        """
        Returns a queryset of workers meeting the criteria to be considered 'missing'

        To be considered missing, a worker must have a stale timestamp.  By default, stale is
        defined here as longer than the ``settings.WORKER_TTL``, or you can specify age as a
        timedelta.

        Args:
            age (datetime.timedelta): Workers who have heartbeats older than this time interval are
                considered missing.

        Returns:
            :class:`django.db.models.query.QuerySet`:  A query set of the Worker objects which
                are considered by Pulp to be 'missing'.
        """
        age_threshold = timezone.now() - age
        return self.filter(last_heartbeat__lt=age_threshold)

    def resource_managers(self):
        """
        Returns a queryset of resource managers.

        Resource managers are identified by their name. Note that some of these may be offline.

        Returns:
            :class:`django.db.models.query.QuerySet`:  A query set of the Worker objects which
                which match the resource manager name.
        """
        return self.filter(name=TASKING_CONSTANTS.RESOURCE_MANAGER_WORKER_NAME)


class Worker(BaseModel):
    """
    Represents a worker

    Fields:

        name (models.TextField): The name of the worker, in the format "worker_type@hostname"
        last_heartbeat (models.DateTimeField): A timestamp of this worker's last heartbeat
    """

    objects = WorkerManager()

    name = models.TextField(db_index=True, unique=True)
    last_heartbeat = models.DateTimeField(auto_now=True)

    @property
    def current_task(self):
        """
        The task this worker is currently executing, if any.

        Returns:
            Task: The currently executing task
        """
        return self.tasks.filter(state="running").first()

    @property
    def online(self):
        """
        Whether a worker can be considered 'online'

        To be considered 'online', a worker must have a recent heartbeat timestamp. "Recent" is
        defined here as "within the pulp process timeout interval".

        Returns:
            bool: True if the worker is considered online, otherwise False
        """
        now = timezone.now()
        age_threshold = now - timedelta(seconds=settings.WORKER_TTL)

        return self.last_heartbeat >= age_threshold

    @property
    def missing(self):
        """
        Whether a worker can be considered 'missing'

        To be considered 'missing', a worker must have a stale timestamp meaning that it was not
        shutdown 'cleanly' and may have died.  Stale is defined here as "beyond the pulp process
        timeout interval".

        Returns:
            bool: True if the worker is considered missing, otherwise False
        """
        now = timezone.now()
        age_threshold = now - timedelta(seconds=settings.WORKER_TTL)

        return self.last_heartbeat < age_threshold

    def save_heartbeat(self):
        """
        Update the last_heartbeat field to now and save it.

        Only the last_heartbeat field will be saved. No other changes will be saved.

        Raises:
            ValueError: When the model instance has never been saved before. This method can
                only update an existing database record.
        """
        self.save(update_fields=["last_heartbeat"])


def _uuid_to_advisory_lock(value):
    return ((value >> 64) ^ value) & 0x7FFFFFFFFFFFFFFF


class Task(BaseModel, AutoDeleteObjPermsMixin, AutoAddObjPermsMixin):
    """
    Represents a task

    Fields:

        state (models.TextField): The state of the task
        name (models.TextField): The name of the task
        logging_cid (models.CharField): The logging CID associated with the task
        started_at (models.DateTimeField): The time the task started executing
        finished_at (models.DateTimeField): The time the task finished executing
        error (models.JSONField): Fatal errors generated by the task
        args (models.JSONField): The JSON serialized arguments for the task
        kwargs (models.JSONField): The JSON serialized keyword arguments for
            the task
        reserved_resources_record (django.contrib.postgres.fields.ArrayField): The reserved
            resources required for the task.

    Relations:

        parent (models.ForeignKey): Task that spawned this task (if any)
        worker (models.ForeignKey): The worker that this task is in
    """

    state = models.TextField(choices=TASK_CHOICES)
    name = models.TextField()
    logging_cid = models.CharField(max_length=256, db_index=True, default="")

    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    error = models.JSONField(null=True)

    args = models.JSONField(null=True, encoder=DjangoJSONEncoder)
    kwargs = models.JSONField(null=True, encoder=DjangoJSONEncoder)

    worker = models.ForeignKey("Worker", null=True, related_name="tasks", on_delete=models.SET_NULL)

    parent_task = models.ForeignKey(
        "Task", null=True, related_name="child_tasks", on_delete=models.SET_NULL
    )
    task_group = models.ForeignKey(
        "TaskGroup", null=True, related_name="tasks", on_delete=models.SET_NULL
    )
    reserved_resources_record = ArrayField(models.CharField(max_length=256), null=True)

    def __str__(self):
        return "Task: {name} [{state}]".format(name=self.name, state=self.state)

    def __enter__(self):
        self.lock = _uuid_to_advisory_lock(self.pk.int)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s);", [self.lock])
            acquired = cursor.fetchone()[0]
        if not acquired:
            raise AdvisoryLockError("Could not acquire lock.")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s);", [self.lock])
            released = cursor.fetchone()[0]
        if not released:
            raise RuntimeError("Lock not held.")

    @staticmethod
    def current():
        """
        Returns:
            pulpcore.app.models.Task: The current task.
        """
        try:
            task_id = os.environ["PULP_TASK_ID"]
        except KeyError:
            task = None
        else:
            task = Task.objects.get(pk=task_id)
        return task

    def set_running(self):
        """
        Set this Task to the running state, save it, and log output in warning cases.

        This updates the :attr:`started_at` and sets the :attr:`state` to :attr:`RUNNING`.
        """
        rows = Task.objects.filter(pk=self.pk, state=TASK_STATES.WAITING).update(
            state=TASK_STATES.RUNNING, started_at=timezone.now()
        )
        if rows != 1:
            _logger.warning(_("Task __call__() occurred but Task %s is not at WAITING") % self.pk)
        self.refresh_from_db()

    def set_completed(self):
        """
        Set this Task to the completed state, save it, and log output in warning cases.

        This updates the :attr:`finished_at` and sets the :attr:`state` to :attr:`COMPLETED`.
        """
        # Only set the state to finished if it's not already in a complete state. This is
        # important for when the task has been canceled, so we don't move the task from canceled
        # to finished.
        rows = (
            Task.objects.filter(pk=self.pk)
            .exclude(state__in=TASK_FINAL_STATES)
            .update(state=TASK_STATES.COMPLETED, finished_at=timezone.now())
        )
        if rows != 1:
            msg = _("Task set_completed() occurred but Task %s is already in final state")
            _logger.warning(msg % self.pk)
        self.refresh_from_db()

    def set_failed(self, exc, tb):
        """
        Set this Task to the failed state and save it.

        This updates the :attr:`finished_at` attribute, sets the :attr:`state` to
        :attr:`FAILED`, and sets the :attr:`error` attribute.

        Args:
            exc (Exception): The exception raised by the task.
            tb (traceback): Traceback instance for the current exception.
        """
        tb_str = "".join(traceback.format_tb(tb))
        rows = (
            Task.objects.filter(pk=self.pk)
            .exclude(state__in=TASK_FINAL_STATES)
            .update(
                state=TASK_STATES.FAILED,
                finished_at=timezone.now(),
                error=exception_to_dict(exc, tb_str),
            )
        )
        if rows != 1:
            raise RuntimeError("Attempt to set a finished task to failed.")
        self.refresh_from_db()

    class Meta:
        indexes = [models.Index(fields=["pulp_created"])]
        permissions = [
            ("manage_roles_task", "Can manage role assignments on task"),
        ]


class TaskGroup(BaseModel):
    description = models.TextField()
    all_tasks_dispatched = models.BooleanField(default=False)

    @staticmethod
    def current():
        """
        Returns:
            pulpcore.app.models.TaskGroup: The task group the current task is being executed and
            belongs to.
        """
        try:
            task_group = Task.current().task_group
        except AttributeError:
            task_group = None
        return task_group

    def finish(self):
        """
        Finalize the task group.

        Set 'all_tasks_dispatched' to True so that API users can know that there are no
        tasks in the group yet to be created.
        """
        self.all_tasks_dispatched = True
        self.save()


class CreatedResource(GenericRelationModel):
    """
    Resources created by the task.

    Relations:
        task (models.ForeignKey): The task that created the resource.
    """

    task = models.ForeignKey(
        Task, related_name="created_resources", default=Task.current, on_delete=models.CASCADE
    )


class TaskSchedule(BaseModel):
    name = models.CharField(max_length=256, unique=True, null=False)
    next_dispatch = models.DateTimeField(default=timezone.now, null=True)
    dispatch_interval = models.DurationField(null=True)
    task_name = models.CharField(max_length=256)
    last_task = models.ForeignKey(Task, null=True, on_delete=models.SET_NULL)

    class Meta:
        permissions = [
            ("manage_roles_taskschedule", "Can manage role assignments on task schedules"),
        ]
