# Copyright 2014-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Boot Resource File."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    'BootResourceFile',
    ]

from django.db.models import (
    CharField,
    ForeignKey,
)
from django.db.models.signals import post_delete
from django.dispatch import receiver
from maasserver import DefaultMeta
from maasserver.enum import (
    BOOT_RESOURCE_FILE_TYPE,
    BOOT_RESOURCE_FILE_TYPE_CHOICES,
)
from maasserver.fields import JSONObjectField
from maasserver.models.bootresourceset import BootResourceSet
from maasserver.models.cleansave import CleanSave
from maasserver.models.largefile import LargeFile
from maasserver.models.timestampedmodel import TimestampedModel


class BootResourceFile(CleanSave, TimestampedModel):
    """File associated with a `BootResourceSet`.

    Each `BootResourceSet` contains a set of files. For user uploaded boot
    resources this is only one file. For synced and generated resources this
    can be multiple files.

    :ivar resource_set: `BootResourceSet` file belongs to. When
        `BootResourceSet` is deleted, this `BootResourceFile` will be deleted.
    :ivar largefile: Actual file information and data. See
        :class:`LargeFile`.
    :ivar filename: Name of the file.
    :ivar filetype: Type of the file. See the vocabulary
        :class:`BOOT_RESOURCE_FILE_TYPE`.
    :ivar extra: Extra information about the file. This is only used
        for synced Ubuntu images.
    """

    class Meta(DefaultMeta):
        unique_together = (
            ('resource_set', 'filetype'),
            )

    resource_set = ForeignKey(
        BootResourceSet, related_name='files', editable=False)

    largefile = ForeignKey(LargeFile, editable=False)

    filename = CharField(max_length=255, editable=False)

    filetype = CharField(
        max_length=20, choices=BOOT_RESOURCE_FILE_TYPE_CHOICES,
        default=BOOT_RESOURCE_FILE_TYPE.ROOT_TGZ, editable=False)

    extra = JSONObjectField(blank=True, default="", editable=False)

    def __unicode__(self):
        return "<BootResourceFile %s/%s>" % (self.filename, self.filetype)


@receiver(post_delete)
def delete_large_file(sender, instance, **kwargs):
    """Call delete on the LargeFile, now that the relation has been removed.
    If this was the only resource file referencing this LargeFile then it will
    be delete.

    This is done using the `post_delete` signal because only then has the
    relation been removed.
    """
    if sender == BootResourceFile:
        try:
            largefile = instance.largefile
        except LargeFile.DoesNotExist:
            largefile = None
        if largefile is not None:
            largefile.delete()
