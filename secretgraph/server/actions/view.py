import logging
from datetime import timedelta as td, datetime as dt

from django.db.models import Q, QuerySet, Subquery
from django.utils import timezone

from ..utils.auth import fetch_by_id
from ..models import Content, ContentAction

logger = logging.getLogger(__name__)


def fetch_clusters(
    query,
    id=None,
    includeTags=None,
    excludeTags=None,
    contentHashes=None,
    minUpdated=None,
    maxUpdated=None,
) -> QuerySet:
    if id:
        query = fetch_by_id(query, id)

    if includeTags or excludeTags or contentHashes:
        incl_filters = Q()
        for i in includeTags or []:
            incl_filters |= Q(contents__tags__tag__startswith=i)

        hash_filters = Q()
        for i in contentHashes or []:
            hash_filters |= Q(contents__contentHash=i)

        excl_filters = Q()
        for i in excludeTags or []:
            excl_filters |= Q(contents__tags__tag__startswith=i)

        query = query.filter(~excl_filters & incl_filters & hash_filters)

    if minUpdated and not maxUpdated:
        maxUpdated = dt.max
    elif maxUpdated and not minUpdated:
        minUpdated = dt.min

    if minUpdated or maxUpdated:
        query = query.filter(
            Q(updated__range=(minUpdated, maxUpdated))
            | Q(contents__updated__range=(minUpdated, maxUpdated))
        )

    return query


class ContentFetchQueryset(QuerySet):
    """
    Tracks usage of contents and mark accordingly Content for removal
    """

    only_direct_fetch_trigger = False
    actions = None

    def __init__(
        self,
        query=None,
        actions=None,
        only_direct_fetch_action_trigger=False,
        **kwargs
    ):
        if actions is None:
            actions = getattr(query, "actions", None)
        if actions is not None:
            self.actions = actions
        self.only_direct_fetch_action_trigger = (
            only_direct_fetch_action_trigger
        )
        kwargs["model"] = kwargs.get("model", None) or query.model
        super().__init__(query=query, **kwargs)

    def _clone(self):
        """
        Return a copy of the current QuerySet. A lightweight alternative
        to deepcopy().
        """
        c = super()._clone()
        c.actions = self.actions
        c.only_direct_fetch_action_trigger = (
            self.only_direct_fetch_action_trigger
        )
        return c

    def fetch_action_trigger(self, objects, direct=True):
        """
        Trigger fetch handling stuff
        fetch=delete after read
        """
        assert self.actions is not None, "actions is None"
        if self.only_direct_fetch_action_trigger and not direct:
            return objects
        if objects is None:
            return objects
        elif isinstance(objects, (Content,)):
            used_actions = ContentAction.objects.filter(
                content=objects, action__in=self.actions
            )
        else:
            # is iterator
            if hasattr(objects, "__next__"):
                objects = list(objects)
            used_actions = ContentAction.objects.filter(
                content__in=objects, action__in=self.actions
            )
        if used_actions:
            used_actions.update(used=True)
            markForDestruction = timezone.now() + td(hours=8)
            Content.objects.filter(
                Q(markForDestruction=None)
                | Q(markForDestruction__gt=markForDestruction),
                id__in=Subquery(used_actions.values("id")),
            ).exclude(
                actions__in=ContentAction.objects.filter(
                    group="fetch", used=False
                )
            ).update(
                markForDestruction=markForDestruction
            )
        return objects

    def __iter__(self):
        for i in self.fetch_action_trigger(super().__iter__(), False):
            yield i

    def __getitem__(self, key):
        return self.fetch_action_trigger(super().__getitem__(key), False)

    def get(self, *args, **kwargs):
        return self.fetch_action_trigger(super().get(*args, **kwargs), False)

    def first(self):
        return self.fetch_action_trigger(super().first(), False)

    def last(self):
        return self.fetch_action_trigger(super().last(), False)

    def earliest(self):
        return self.fetch_action_trigger(super().earliest(), False)

    def latest(self):
        return self.fetch_action_trigger(super().latest(), False)


def fetch_contents(
    query,
    actions,
    id=None,
    includeTags=None,
    excludeTags=None,
    contentHashes=None,
    noFetch=False,
    minUpdated=None,
    maxUpdated=None,
) -> QuerySet:
    assert actions is not None, "actions is None"
    assert not isinstance(actions, str), "actions is str"
    if id:
        query = fetch_by_id(query, id, check_content_hash=True)
    if includeTags or excludeTags or contentHashes:
        incl_filters = Q()
        hash_filters = Q()
        excl_filters = Q()
        for i in includeTags or []:
            incl_filters |= Q(tags__tag__startswith=i)

        for i in contentHashes or []:
            hash_filters |= Q(contentHash=i)

        for i in excludeTags or []:
            excl_filters |= Q(tags__tag__startswith=i)
        query = query.filter((~excl_filters) & incl_filters & hash_filters)

    if minUpdated and not maxUpdated:
        maxUpdated = dt.max
    elif maxUpdated and not minUpdated:
        minUpdated = dt.min

    if minUpdated or maxUpdated:
        query = query.filter(updated__range=(minUpdated, maxUpdated))
    return ContentFetchQueryset(
        query.query, actions=actions, only_direct_fetch_action_trigger=noFetch
    )
