
from itertools import product, islice
import uuid

from django.db import transaction, models
from django.db.utils import IntegrityError

from ..constants import DeleteRecursive


def deleteContentCb(sender, instance, **kwargs):
    from ..models import ContentReference
    references = ContentReference.objects.filter(
        target=instance
    )
    other_references = ContentReference.objects.filter(
        ~models.Q(target=instance)
    )
    nogroup_references = references.filter(
        deleteRecursive=DeleteRecursive.NO_GROUP
    )

    recursive_references = references.filter(
        deleteRecursive=DeleteRecursive.TRUE
    )
    # delete recursive connected contents
    sender.objects.filter(
        references__in=recursive_references
    ).delete()

    # delete contents if group vanishes and NO_GROUP is set
    delete_ids = []
    for content_id in sender.objects.filter(
        models.Q(references__in=nogroup_references)
    ).annotate(
        relevant_groups=models.Subquery(
            nogroup_references.filter(
                source=models.OuterRef("pk")
            ).annotate(
                amount=models.Count("group", distinct=True)
            )
        )
    ).filter(
        relevant_groups__amount__gt=models.Subquery(
            other_references.filter(
                source=models.OuterRef("pk"),
                group__in=models.OuterRef("relevant_groups.group")
            ).annotate(
                amount=models.Count("group", distinct=True)
            ).values("amount")
        )
    ).values_list("pk", flat=True):
        delete_ids.append(content_id)
    sender.objects.filter(id__in=delete_ids).delete()


def deleteEncryptedFileCb(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(False)


def generateFlexid(sender, instance, force=False, **kwargs):
    from .models import Cluster, Content
    if not instance.flexid or force:
        for i in range(0, 1000):
            if i >= 999:
                raise ValueError(
                    'A possible infinite loop was detected'
                )
            instance.flexid = uuid.uuid4()
            try:
                with transaction.atomic():
                    instance.save(
                        update_fields=["flexid"]
                    )
                break
            except IntegrityError:
                pass

        # if issubclass(sender, Content):
        #    fname = instance.file.name
        #    instance.file.save("", instance.file.open("rb"))
        #    instance.file.storage.delete(fname)
        #    instance.tags.filter(tag__startswith="id=").update(
        #        tag=f"id={instance.flexid}"
        #    )
        # el
        if issubclass(sender, Cluster) and force:
            for c in instance.contents.all():
                generateFlexid(Content, c, True)


def regenerateKeyHash(sender, force=False, **kwargs):
    from .utils.misc import hash_object, calculate_hashes
    from .models import Content, ContentTag
    contents = Content.objects.filter(
        tags__tag="type=PublicKey"
    )
    # calculate for all old hashes
    if not force:
        contents = contents.exclude(
            contentHash__regex='^.{%d}$' % len(hash_object(b""))
        )

    # distinct on contentHash field currently only for postgresql
    for content in contents:
        chashes = calculate_hashes(content.load_pubkey())
        add_to = 0
        for i in chashes:
            if i == content.contentHash:
                break
            add_to += 1
        if add_to == 0:
            continue

        tags = map(lambda x: 'key_hash=%s' % x, chashes)
        batch_size = 1000
        final_tags = (
            ContentTag(tag=tag, content=content)
            for (tag, c) in product(
                tags[:add_to],
                Content.objects.exclude(
                    tags__tag=tags[0]
                ).filter(
                    models.Q(tags__tag__in=tags[add_to:])
                )
            )
        )
        while True:
            batch = list(islice(final_tags, batch_size))
            if not batch:
                break
            # ignore duplicate key_hash entries
            ContentTag.objects.bulk_create(batch, ignore_conflicts=True)
        Content.objects.filter(
            contentHash__in=chashes[1:],
            tags__tag="type=PublicKey"
        ).update(contentHash=chashes[0])


def fillEmptyFlexidsCb(sender, **kwargs):
    from .models import Cluster, Content
    for c in Cluster.objects.filter(flexid=None):
        generateFlexid(Cluster, c, False)
    for c in Content.objects.filter(flexid=None):
        generateFlexid(Content, c, False)
