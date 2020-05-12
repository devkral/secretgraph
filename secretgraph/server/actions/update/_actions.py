__all__ = ["create_actions_func"]


import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.db.models import Q
from django.utils import timezone

from ...actions.handler import ActionHandler
from ...models import (
    Action, Content, Cluster, ContentAction
)
from ...utils.auth import retrieve_allowed_objects
from ...utils.misc import hash_object


def create_actions_func(
    obj, actionlist, request, addonly=False, default_key=None
):
    final_actions = []
    final_content_actions = []
    action_types = set()
    if not default_key:
        default_key = request.headers.get("Authorization", "").replace(
            " ", ""
        ).split(",", 1)[0].split(":", 1)[-1]
        try:
            default_key = base64.b64decode(default_key)
        except Exception:
            default_key = None

    if isinstance(obj, Content):
        cluster = obj.cluster
        content = obj
        delete_q = Q(content_action__content=content)
    elif isinstance(obj, Cluster):
        cluster = obj
        content = None
        delete_q = Q(content_action=None)
    else:
        raise ValueError("Invalid type")

    for action in actionlist:
        action_key = action.get("key")
        if isinstance(action_key, bytes):
            pass
        elif isinstance(action_key, str):
            action_key = base64.base64_decode(action_key)
        elif default_key:
            action_key = default_key
        else:
            raise ValueError("No key specified/available")

        action_key_hash = hash_object(action_key)
        action_value = action["value"]
        if isinstance(str, action_value):
            action_value = json.loads(action_value)
        action_value = ActionHandler.clean_action(
            action_value, request, content
        )

        # create Action object
        aesgcm = AESGCM(action_key)
        nonce = os.urandom(13)
        # add content_action
        group = action_value.pop("content_action_group") or ""
        if content:
            c = ContentAction(
                content=content,
                group=group
            )
            final_content_actions.append(c)

        action = Action(
            value=aesgcm.encode(
                nonce,
                json.dumps(action_value).encode("utf-8"),
                None
            ),
            start=action.get("start", timezone.now()),
            stop=action.stop,
            key_hash=action_key_hash,
            nonce=base64.b64encode(nonce).decode("ascii"),
            content_action=c
        )
        action.action_type = action_value["action"]
        action_types.add(action_value["action"])
        final_actions.append(action)

    def save_func():
        result = retrieve_allowed_objects(
            request, "manage", cluster.actions.all()
        )
        if not addonly:
            # delete old actions of obj, if allowed to
            actions = result["objects"].filter(delete_q)
            if content:
                # recursive deletion
                ContentAction.objects.filter(
                    action__in=actions
                ).delete()
            else:
                # direct deletion
                actions.delete()
        if content:
            ContentAction.objects.bulk_create(final_content_actions)
        cluster.actions.bulk_create(final_actions)
    setattr(save_func, "actions", final_actions)
    setattr(save_func, "action_types", action_types)
    setattr(save_func, "key", default_key)
    return save_func
