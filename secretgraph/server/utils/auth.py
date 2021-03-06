import base64
import json
import logging
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.apps import apps
from django.db import models
from django.utils import timezone
from graphql_relay import from_global_id

from ..actions.handler import ActionHandler
from ..models import Action, Cluster, Content
from .misc import calculate_hashes

logger = logging.getLogger(__name__)


_cached_classes = {"Content", "Cluster", "Action"}


class LazyViewResult(object):
    _result_dict = None

    def __init__(self, request, *viewResults, authset=None, scope="view"):
        self._result_dict = {}
        self.request = request
        self.authset = authset
        self.scope = scope
        for r in viewResults:
            self._result_dict[r["objects"].model.__name__] = r
        if self.authset is None:
            self.authset = (
                request.headers.get("Authorization", "")
                .replace(" ", "")
                .split(",")
            )

    def __getitem__(self, item):
        if item in _cached_classes:
            if item not in self._result_dict:
                self._result_dict[item] = retrieve_allowed_objects(
                    self.request,
                    self.scope,
                    apps.get_model("secretgraph", item).objects.all(),
                    authset=self.authset,
                )
            return self._result_dict[item]
        if item in {"authset", "scope"}:
            return self.authset
        raise KeyError()

    def get(self, item, default=None):
        try:
            return self.__getitem__(item)
        except KeyError:
            return default


def initializeCachedResult(
    request, *viewResults, authset=None, scope="view", name="secretgraphResult"
):
    if not getattr(request, name, None):
        setattr(
            request,
            name,
            LazyViewResult(
                request, *viewResults, scope=scope, authset=authset
            ),
        )
    return getattr(request, name)


_allowed_types = {"Cluster"}


def retrieve_allowed_objects(request, scope, query, authset=None):
    if authset is None:
        authset = (
            request.headers.get("Authorization", "")
            .replace(" ", "")
            .split(",")
        )
    authset = set(authset)
    now = timezone.now()
    # cleanup expired Contents
    Content.objects.filter(markForDestruction__lte=now).delete()
    if query.model == Cluster:
        Cluster.objects.annotate(models.Count("contents")).filter(
            markForDestruction__lte=now, contents__count=0
        ).delete()
    # for sorting. First action is always the most important action
    # importance is higher by start date, newest (here id)
    pre_filtered_actions = (
        Action.objects.select_related("cluster")
        .filter(start__lte=now)
        .filter(models.Q(stop__isnull=True) | models.Q(stop__gte=now))
        .order_by("-start", "-id")
    )
    if isinstance(query.model, Content):
        pre_filtered_actions = pre_filtered_actions.filter(
            models.Q(contentAction__isnull=True)
            | models.Q(contentAction__content__in=query)
        )
    clusters = set()
    all_filters = models.Q()
    returnval = {
        "authset": authset,
        "scope": scope,
        "rejecting_action": None,
        "clusters": {},
        "forms": {},
        "actions": Action.objects.none(),
        "action_key_map": {},
        "required_keys_clusters": {},
        "required_keys_contents": {},
    }
    for item in authset:
        # harden against invalid input, e.g. object view produces empty strings
        if not item:
            continue
        spitem = item.split(":", 1)
        if len(spitem) != 2:
            continue

        clusterflexid, action_key = spitem
        _type = "Cluster"
        try:
            _type, clusterflexid = from_global_id(clusterflexid)
        finally:
            if _type not in _allowed_types:
                continue
        try:
            clusterflexid = UUID(clusterflexid)
        except ValueError:
            continue
        try:
            action_key = base64.b64decode(action_key)
        finally:
            if not isinstance(action_key, bytes) or len(action_key) != 32:
                continue
        aesgcm = AESGCM(action_key)
        keyhashes = calculate_hashes(action_key)

        actions = pre_filtered_actions.filter(
            cluster__flexid=clusterflexid, keyHash__in=keyhashes
        )
        if not actions:
            continue

        filters = models.Q()
        # 0 default
        # 1 normal
        # 2 owner
        # 3 special
        accesslevel = 0
        for action in actions:
            action_dict = json.loads(
                aesgcm.decrypt(
                    base64.b64decode(action.nonce), action.value, None
                )
            )
            result = ActionHandler.handle_action(
                query.model,
                action_dict,
                scope=scope,
                action=action,
                accesslevel=accesslevel,
                request=request,
                authset=authset,
            )
            if result is None:
                continue
            if result is False:
                returnval["rejecting_action"] = (action, action_dict)
                returnval["objects"] = query.none()
                return returnval
            if action.contentAction:
                required_keys_dict = returnval[
                    "required_keys_contents"
                ].setdefault(action.contentAction.content_id, {})
            else:
                required_keys_dict = returnval[
                    "required_keys_clusters"
                ].setdefault(action.cluster_id, {})

            foundaccesslevel = result["accesslevel"]

            if accesslevel < foundaccesslevel:
                accesslevel = foundaccesslevel
                filters = result.get("filters", models.Q())
                form = result.get("form")
                if form:
                    returnval["forms"] = {action.id: form}

                required_keys_dict[(action_dict["action"], action.keyHash)] = {
                    "id": action.id,
                    "requiredKeys": form.get("requiredKeys", []),
                    "allowedTags": form.get("allowedTags"),
                }
            elif accesslevel == foundaccesslevel:
                filters &= result.get("filters", models.Q())
                form = result.get("form")
                if form:
                    returnval["forms"].setdefault(action.id, form)
                required_keys_dict.setdefault(
                    (action_dict["action"], action.keyHash),
                    {
                        "requiredKeys": form.get("requiredKeys", []),
                        "allowedTags": form.get("allowedTags"),
                    },
                )

            if action.keyHash != keyhashes[0]:
                Action.objects.filter(keyHash=action.keyHash).update(
                    keyHash=keyhashes[0]
                )
        returnval["clusters"][clusterflexid] = {
            "filters": filters,
            "accesslevel": accesslevel,
            "action_key": action_key,
            "actions": actions,
        }
        returnval["actions"] |= actions
        for h in keyhashes:
            returnval["action_key_map"][h] = action_key
        clusters.add(clusterflexid)
        if issubclass(query.model, Cluster):
            all_filters |= filters & models.Q(id=actions[0].cluster_id)
        else:
            all_filters |= filters & models.Q(cluster_id=actions[0].cluster_id)

    if issubclass(query.model, Cluster):
        all_filters &= models.Q(
            id__in=list(returnval["required_keys_clusters"].keys())
        ) | models.Q(public=True)
    elif issubclass(query.model, Content):
        all_filters &= (
            models.Q(tags__tag="state=public")
            | models.Q(id__in=list(returnval["required_keys_contents"].keys()))
            | models.Q(
                cluster_id__in=list(returnval["required_keys_clusters"].keys())
            )
        )
    else:
        assert issubclass(query.model, Action), "invalid type %r" % query.model
        all_filters &= models.Q(
            cluster_id__in=list(returnval["required_keys_clusters"].keys())
        )
    # for sorting. First action is always the most important action
    # importance is higher by start date, newest (here id)
    returnval["actions"] = Action.objects.filter(
        id__in=models.Subquery(returnval["actions"].values("id"))
    ).order_by("-start", "-id")
    returnval["objects"] = query.filter(id__in=query.filter(all_filters))
    return returnval


def fetch_by_id(
    query,
    flexids,
    prefix="",
    type_name=None,
    check_content_hash=False,
    limit_ids=1,
):
    # without auth check! do it before
    type_name = type_name or query.model.__name__
    if isinstance(flexids, str):
        flexids = [flexids]
    else:
        flexids = flexids[:limit_ids]
    if not flexids:
        raise ValueError("No id specified")
    flexid_set = set()
    chash_set = set()
    for f in flexids:
        name = type_name
        try:
            name, f = from_global_id(f)
        except Exception:
            pass
        try:
            f = UUID(f)
            addto = flexid_set
        except ValueError:
            if check_content_hash:
                addto = chash_set
            else:
                raise ValueError("Malformed id")
        if type_name != name:
            raise ValueError(
                "No {} Id ({})".format(query.model.__name__, type_name)
            )
        addto.add(f)
    filters = {f"{prefix}flexid__in": flexid_set}
    if chash_set:
        filters[f"{prefix}contentHash__in"] = chash_set
    return query.filter(**filters)


def id_to_result(request, id, klasses, scope="view", authset=None):
    if not isinstance(klasses, tuple):
        klasses = (klasses,)
    if isinstance(id, str):
        type_name, flexid = from_global_id(id)
        try:
            flexid = UUID(flexid)
        except ValueError:
            raise ValueError("Malformed id")
        result = None
        for klass in klasses:
            if type_name == klass.__name__:
                if scope == "view" and type(id).__name__ in _cached_classes:
                    result = initializeCachedResult(request, authset=authset)[
                        type(id).__name__
                    ]
                    result = result.copy()
                    result["objects"] = result["objects"].filter(flexid=flexid)
                else:
                    result = retrieve_allowed_objects(
                        request,
                        scope,
                        klass.objects.filter(flexid=flexid),
                        authset=authset,
                    )
                break
        if not result:
            raise ValueError(
                "Only for {} (ids)".format(
                    ",".join(map(lambda x: x.__name__, klasses))
                )
            )
    elif not isinstance(id, klasses):
        raise ValueError(
            "Only for {}".format(",".join(map(lambda x: x.__name__, klasses)))
        )
    else:
        if scope == "view" and type(id).__name__ in _cached_classes:
            result = initializeCachedResult(request, authset=authset)[
                type(id).__name__
            ]
            result = result.copy()
            result["objects"] = result["objects"].filter(pk=id.pk)
        else:
            result = retrieve_allowed_objects(
                request,
                scope,
                type(id).objects.filter(pk=id.pk),
                authset=authset,
            )
    return result
