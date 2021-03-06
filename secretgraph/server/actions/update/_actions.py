__all__ = ["create_actions_fn"]


import base64
import json
import os
from contextlib import nullcontext

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.db.models import Q
from django.utils import timezone

from ...utils.auth import retrieve_allowed_objects
from ...utils.misc import hash_object, refresh_fields
from ...actions.handler import ActionHandler
from ...models import Action, Content, Cluster, ContentAction


def create_actions_fn(
    obj, actionlist, request, default_key=None, authset=None
):
    add_actions = []
    modify_actions = {}
    delete_actions = set()
    action_types = set()
    if not default_key:
        default_key = (
            request.headers.get("Authorization", "")
            .replace(" ", "")
            .split(",", 1)[0]
            .split(":", 1)[-1]
        )
        try:
            default_key = base64.b64decode(default_key)
        except Exception:
            default_key = None

    if isinstance(obj, Content):
        cluster = obj.cluster
        content = obj
    elif isinstance(obj, Cluster):
        cluster = obj
        content = None
    else:
        raise ValueError("Invalid type")

    result = retrieve_allowed_objects(request, "manage", cluster.actions.all())

    for action in actionlist:
        if action["value"] == "delete":
            action_value = "delete"
        else:
            action_value = action["value"]
            if isinstance(action_value, str):
                action_value = json.loads(action_value)
        if action_value == "delete":
            if "idOrHash" in action:
                if action["idOrHash"] in modify_actions:
                    raise ValueError("update id in delete set")
                delete_actions.add(action["idOrHash"])
            continue
        action_key = action.get("key")
        if isinstance(action_key, bytes):
            pass
        elif isinstance(action_key, str):
            action_key = base64.b64decode(action_key)
        elif default_key:
            action_key = default_key
        else:
            raise ValueError("No key specified/available")

        action_key_hash = hash_object(action_key)
        action_value_result = ActionHandler.clean_action(
            action_value, request, authset, content
        )

        # create Action object
        aesgcm = AESGCM(action_key)
        nonce = os.urandom(13)
        # add content_action
        group = action_value.pop("contentActionGroup", "") or ""
        if action.get("idOrHash"):
            actionObj = (
                result["objects"]
                .filter(
                    Q(id=action["idOrHash"]) | Q(keyHash=action["idOrHash"])
                )
                .first()
            )
            if not actionObj:
                continue
        elif content:
            actionObj = Action(contentAction=ContentAction(content=content))
        else:
            actionObj = Action()
        if content:
            actionObj.contentAction.group = group
        actionObj.value = aesgcm.encrypt(
            nonce, json.dumps(action_value_result).encode("utf-8"), None
        )
        actionObj.start = action.get("start", timezone.now())
        actionObj.stop = action.get("start", None)
        actionObj.keyHash = action_key_hash
        actionObj.nonce = base64.b64encode(nonce).decode("ascii")
        actionObj.cluster = cluster
        actionObj.action_type = action_value["action"]
        action_types.add(action_value["action"])
        if actionObj.id:
            if actionObj.id in delete_actions:
                raise ValueError("update id in delete set")
            modify_actions[actionObj.id] = actionObj
        else:
            add_actions.append(actionObj)

    create = not cluster.pk
    if None in delete_actions:
        if content:
            delete_q = Q()
        else:
            delete_q = Q(ContentAction__isnull=True)
    else:
        ldelete_actions = list(delete_actions)
        delete_q = Q(id__in=ldelete_actions) | Q(keyHash__in=ldelete_actions)

    def save_fn(context=nullcontext):
        if callable(context):
            context = context()
        with context:
            if not create and delete_q:
                # delete old actions of obj, if allowed to
                actions = result["objects"].filter(delete_q)
                if content:
                    # recursive deletion
                    ContentAction.objects.filter(
                        action__in=actions,
                        content=content,
                    ).delete()
                else:
                    # direct deletion
                    actions.delete()
            if add_actions:
                ContentAction.objects.bulk_create(
                    map(
                        lambda c: c.contentAction,
                        filter(lambda x: x.contentAction, add_actions),
                    )
                )
            if create:
                Action.objects.bulk_create(
                    refresh_fields(add_actions, "cluster")
                )
            else:
                if modify_actions:
                    ContentAction.objects.bulk_update(
                        [
                            c.contentAction
                            for c in filter(
                                lambda x: x.contentAction,
                                modify_actions.values(),
                            )
                        ]
                    )
                Action.objects.bulk_create(add_actions)
                Action.objects.bulk_update(modify_actions.values())

    setattr(save_fn, "actions", [*add_actions, *modify_actions.values()])
    setattr(save_fn, "action_types", action_types)
    setattr(save_fn, "key", default_key)
    return save_fn
