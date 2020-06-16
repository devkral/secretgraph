__all__ = [
    "create_content", "update_content", "create_key_func", "transfer_value"
]


import base64
import json
import logging
from email.parser import BytesParser
from itertools import chain

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_der_public_key
from django.core.files.base import ContentFile, File
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from django.test import Client
from graphql_relay import from_global_id
from rdflib import Graph

from ....constants import TransferResult
from ....utils.auth import (
    fetch_by_flexid, initializeCachedResult, retrieve_allowed_objects
)
from ....utils.conf import get_requests_params
from ....utils.encryption import default_padding, encrypt_into_file
from ....utils.misc import (
    calculate_hashes, get_secrets, hash_object, refresh_fields
)
from ...models import Cluster, Content, ContentReference, ContentTag
from ._actions import create_actions_func

logger = logging.getLogger(__name__)

len_default_hash = len(hash_object(b""))


def _transform_info_tags(content, objdata):
    info_tags = []
    key_hashes = set()
    content_type = None
    content_state = None
    for i in set(objdata.get("info") or []):
        if i.startswith("id="):
            logger.warning("id is an invalid tag (autogenerated)")
            continue
        if i.startswith("state="):
            if content_state is not None:
                raise ValueError("state=<foo> is a unique key")
            content_state = i.split("=", 1)[1]
            continue
        elif i.startswith("type="):
            if content_type is not None:
                raise ValueError("type=<foo> is a unique key")
            content_type = i.split("=", 1)[1]
        elif i.startswith("key_hash="):
            key_hash = i.split("=", 1)[1]
            if len_default_hash == len(key_hash):
                key_hashes.add(key_hash)
        if len(i) > 8000:
            raise ValueError("Info tag too big")
        info_tags.append(ContentTag(content=content, tag=i))
    return info_tags, key_hashes, content_type, content_state or "default"


def _transform_key_into_dataobj(key_obj, content=None):
    if isinstance(key_obj.get("privateKey"), str):
        key_obj["privateKey"] = base64.b64decode(key_obj["privateKey"])
    if isinstance(key_obj.get("publicKey"), str):
        key_obj["publicKey"] = base64.b64decode(key_obj["publicKey"])
    if isinstance(key_obj.get("nonce"), str):
        key_obj["nonce"] = base64.b64decode(key_obj["nonce"])
    if key_obj.get("privateKey"):
        if not key_obj.get("nonce"):
            raise ValueError("encrypted private key requires nonce")
    if not key_obj.get("publicKey"):
        raise ValueError("No public key")
    try:
        if isinstance(key_obj["publicKey"], bytes):
            key_obj["publicKey"] = load_der_public_key(
                key_obj["publicKey"], default_backend()
            )
        elif isinstance(key_obj["publicKey"], File):
            key_obj["publicKey"] = load_der_public_key(
                key_obj["publicKey"].read(), default_backend()
            )
        key_obj["publicKey"] = key_obj["publicKey"].public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
    except Exception as exc:
        # logger.debug("loading public key failed", exc_info=exc)
        raise ValueError("Invalid public key") from exc
    if content:
        if content.value.open("rb").read() != key_obj["publicKey"]:
            raise ValueError("Cannot change public key")
    hashes = calculate_hashes(key_obj["publicKey"])
    hashes_info = tuple(map(
        lambda x: f"key_hash={x}", hashes
    ))

    return (
        hashes,
        {
            "nonce": b"",
            "value": key_obj["publicKey"],
            "info": chain(
                ["type=PublicKey"],
                hashes_info,
                key_obj.get("publicInfo") or []
            ),
            "contentHash": hashes[0]
        },
        {
            "nonce": key_obj["nonce"],
            "value": key_obj["privateKey"],
            "info": chain(
                ["type=PrivateKey"],
                hashes_info,
                key_obj.get("privateInfo") or []
            ),
            "contentHash": None
        } if key_obj.get("privateKey") else None
    )


def _update_or_create_content_or_key(
    request, content, objdata, authset, is_key, required_keys
):
    if isinstance(objdata.get("cluster"), str):
        objdata["cluster"] = fetch_by_flexid(
            retrieve_allowed_objects(
                request, "update", Cluster.objects.all(), authset=authset
            )["objects"],
            objdata["cluster"]
        ).filter(markForDestruction=None).first()
    if objdata.get("cluster"):
        content.cluster = objdata["cluster"]
    if not getattr(content, "cluster", None):
        raise ValueError("No cluster specified")

    create = not content.id

    # if create checked in parent function
    if objdata.get("value"):
        # normalize nonce and check constraints
        try:
            if isinstance(objdata["nonce"], bytes):
                checknonce = objdata["nonce"]
                objdata["nonce"] = base64.b64encode(checknonce)
            else:
                checknonce = base64.b64decode(objdata["nonce"])
        except Exception:
            # no nonce == trigger encryption
            objdata["value"], objdata["nonce"], objdata["key"] = \
                encrypt_into_file(
                    objdata["value"],
                    key=objdata.get("key") or None
                )
        # is public key? then ignore nonce checks
        if not is_key or not objdata.get("contentHash"):
            if len(checknonce) != 13:
                raise ValueError("invalid nonce size")
            if checknonce.count(b"\0") == len(checknonce):
                raise ValueError("weak nonce")
        content.nonce = objdata["nonce"]

        if isinstance(objdata["value"], bytes):
            objdata["value"] = ContentFile(objdata["value"])
        elif isinstance(objdata["value"], str):
            objdata["value"] = ContentFile(base64.b64decode(objdata["value"]))
        else:
            objdata["value"] = File(objdata["value"])

        def save_func_value():
            content.file.delete(False)
            content.file.save("", objdata["value"])
    else:
        def save_func_value():
            content.save()

    final_info_tags = None
    if objdata.get("info") is not None:
        final_info_tags, key_hashes_info, content_type, content_state = \
            _transform_info_tags(content, objdata)
        if is_key:
            if content_state not in {"public", "internal", "default"}:
                raise ValueError(
                    "%s is an invalid state for key", content_state
                )
        else:
            if content_type in {"PrivateKey", "PublicKey", None}:
                raise ValueError(
                    "%s is an invalid type or not set", content_type
                )
            elif content_type == "Config" and content_state not in {
                "default", "internal"
            }:
                raise ValueError(
                    "%s is an invalid state for Config", content_type
                )
            elif content_state not in {
                "draft", "public", "internal", "default"
            }:
                raise ValueError(
                    "%s is an invalid state for content", content_state
                )
    else:
        key_hashes_info = set()
        content_type = None
        content_state = None

    # cannot change because of special key transformation
    chash = objdata.get("contentHash")
    if chash is not None:
        if len(chash) not in (0, len_default_hash):
            raise ValueError("Invalid hashing algorithm used for contentHash")
        if len(chash) == 0:
            content.contentHash = None
        else:
            content.contentHash = chash

    final_references = None
    key_hashes_ref = set()
    if objdata.get("references") is not None:
        final_references = []
        for ref in objdata["references"]:
            if isinstance(ref["target"], Content):
                targetob = ref["target"]
            else:
                type_name = "Content"
                try:
                    type_name, ref["target"] = from_global_id(ref["target"])
                except Exception:
                    pass
                if type_name != "Content":
                    raise ValueError("No Content Id")
                if isinstance(ref["target"], int):
                    q = Q(id=ref["target"])
                else:
                    _refs1 = Subquery(
                        ContentTag.objects.filter(
                            tag=f"key_hash={ref['target']}",
                            content_id=OuterRef("content_id")
                        ).values("pk")
                    )
                    _refs2 = Subquery(
                        ContentTag.objects.filter(
                            # for correct chaining
                            tag="type=PublicKey",
                            content_id=OuterRef("pk"),
                            content__info__in=_refs1
                        ).values("pk")
                    )
                    # the direct way doesn't work
                    # subquery is necessary for chaining operations correctly
                    q = (
                        Q(info__tag=f"id={ref['target']}") |
                        Q(info__in=_refs2)
                    )

                targetob = Content.objects.filter(
                    q, markForDestruction=None
                ).first()
            if not targetob:
                continue
            if ref.get("extra") and len(ref["extra"]) > 8000:
                raise ValueError("Extra tag too big")
            refob = ContentReference(
                source=content,
                target=targetob, group=ref.get("group") or "",
                extra=ref.get("extra") or ""
            )
            if refob.group in {"key", "transfer"}:
                refob.deleteRecursive = None
                if refob.group == "key":
                    key_hashes_ref.add(targetob.contentHash)
                if targetob.contentHash not in key_hashes_info:
                    raise ValueError("Key hash not found in info")
            final_references.append(refob)
    elif create:
        final_references = []

    inner_key = objdata.get("key")
    if inner_key:
        if isinstance(inner_key, str):
            inner_key = base64.b64decode(inner_key)
        # last resort
        if not is_key and not key_hashes_ref and final_references is not None:
            default_keys = initializeCachedResult(
                request, authset=authset
            )["Content"]["objects"].filter(
                cluster=content.cluster,
                info__tag="type=PublicKey"
            )

            if required_keys:
                default_keys |= Content.objects.filter(
                    info__tag="type=PublicKey",
                    info__tag__in=map(
                        lambda x: f"key_hash={x}",
                        required_keys
                    )
                )

            for keyob in default_keys.distinct():
                refob = ContentReference(
                    target=keyob, group="key", deleteRecursive=None,
                    extra=keyob.encrypt(
                        inner_key,
                        default_padding
                    )
                )
                final_references.append(refob)
                key_hashes_info.add(keyob.contentHash)
                final_info_tags.append(ContentTag(
                    tag=f"key_hash={keyob.contentHash}"
                ))
    if final_info_tags is not None:
        if content_type == "PrivateKey" and len(key_hashes_info) < 1:
            raise ValueError(
                "requires hash of decryption key as key_hash tag"
            )
        elif (
            content_type == "PublicKey" and
            content.contentHash not in key_hashes_info
        ):
            raise ValueError(
                ">=1 key_hash info tags required for PublicKey (own hash)"
            )
        elif not key_hashes_info.issuperset(required_keys):
            raise ValueError(
                "missing required keys"
            )
    if final_references is not None:
        if not is_key and len(key_hashes_ref) < 1:
            raise ValueError(
                ">=1 key references required for content"
            )
    if objdata.get("actions") is not None:
        actions_save_func = create_actions_func(
            content, objdata["actions"], request, authset=authset
        )
    else:
        def actions_save_func():
            pass

    def save_func():
        save_func_value()
        if final_info_tags is not None:
            if create:
                ContentTag.objects.bulk_create(refresh_fields(
                    final_info_tags, "content"
                ))
            else:
                # simply ignore id=, can only be changed in regenerateFlexid
                content.info.exclude(
                    Q(tag__startswith="id=")
                ).delete()
                ContentTag.objects.bulk_create(
                    final_info_tags, "content"
                )
            if content_state != "default":
                content.info.create(tag="state=%s" % content_state)

        # create id tag after object was created or update it
        content.info.update_or_create(
            defaults={"tag": f"id={content.flexid}"},
            tag__startswith="id="
        )
        if final_references is not None:
            if not create:
                if is_key:
                    refs = content.references.exclude(group="public_key")
                else:
                    refs = content.references.all()
                refs.delete()
            # must refresh in case a new target is injected and saved before
            ContentReference.objects.bulk_create(refresh_fields(
                final_references, "source", "target"
            ))
        if final_info_tags is not None and content_state == "default":
            if content.cluster.public:
                if is_key:
                    # add public when action_key is public
                    g = Graph()
                    g.parse(content.cluster.publicInfo, "turtle")
                    secrets = get_secrets(g)
                    public_action_secrets = set()
                    for i in secrets:
                        splitted = i.split(b":", 1)
                        if len(splitted) == 2 and splitted[0] != "":
                            public_action_secrets.add(splitted[1])
                            break
                    if public_action_secrets.intersection(
                        key_hashes_info
                    ):
                        content.info.create(tag="state=public")
                    else:
                        content.info.create(tag="state=internal")
                elif content_type == "Config":
                    content.info.create(tag="state=internal")
                else:
                    content.info.create(tag="state=draft")
        actions_save_func()
    setattr(save_func, "content", content)
    return save_func


def create_key_func(
    request, objdata, key=None, authset=None
):
    key_obj = objdata.get("key")
    if not key_obj:
        raise ValueError("Requires key")
    if isinstance(objdata.get("cluster"), str):
        type_name, objdata["cluster"] = from_global_id(objdata["cluster"])
        if type_name != "Cluster":
            raise ValueError("Requires Cluster id")
        objdata["cluster"] = fetch_by_flexid(
            initializeCachedResult(
                request, authset=authset
            )["Cluster"]["objects"],
            objdata["cluster"]
        ).filter(markForDestruction=None).first()
    if not objdata.get("cluster"):
        raise ValueError("No cluster")

    hashes, public, private = _transform_key_into_dataobj(key_obj)
    publickey_content = None
    if objdata["cluster"].id:
        publickey_content = Content.objects.filter(
            cluster=objdata["cluster"],
            info__tag="type=PublicKey",
            info__tag__in=map(lambda x: f"key_hash={x}", hashes)
        ).first()
    publickey_content = \
        publickey_content or Content(cluster=objdata["cluster"])
    if key:
        private["info"] = chain(
            private["info"],
            ["key_hash={}".format(hash_object(key))]
        )
    public["references"] = objdata.get("references")
    public["actions"] = objdata.get("actions")
    public = _update_or_create_content_or_key(
        request, publickey_content, public, authset, True, []
    )
    if private:
        private["references"] = [{
            "target": publickey_content,
            "group": "public_key",
            "deleteRecursive": True
        }]
        private = _update_or_create_content_or_key(
            request, Content(cluster=objdata["cluster"]), private, authset,
            True, []
        )

    def func():
        return public(), private and private()

    return func


def create_content(
    request, objdata, key=None, authset=None, required_keys=None
):
    value_obj = objdata.get("value", {})
    key_obj = objdata.get("key")
    if not value_obj and not key_obj:
        raise ValueError("Requires value or key")
    if value_obj and key_obj:
        raise ValueError("Can only specify one of value or key")

    if key_obj:
        # has removed key argument for only allowing complete key
        save_func = create_key_func(
            request, objdata, authset=authset
        )

        with transaction.atomic():
            return save_func()[0]
    else:
        newdata = {
            "cluster": objdata.get("cluster"),
            "references": objdata.get("references"),
            "contentHash": objdata.get("contentHash"),
            "info": value_obj.get("info"),
            "actions": objdata.get("actions"),
            "key": key,
            **value_obj
        }
        content_obj = Content()
        save_func = _update_or_create_content_or_key(
            request, content_obj, newdata, authset, False,
            required_keys or []
        )

        with transaction.atomic():
            return save_func()


def update_content(
    request, content, objdata, key=None, authset=None,
    required_keys=None
):
    assert content.id
    is_key = False
    # TODO: maybe allow updating both keys (only info)
    if content.info.filter(tag="type=PublicKey"):
        is_key = True
        key_obj = objdata.get("key")
        if not key_obj:
            raise ValueError("Cannot transform key to content")

        hashes, newdata, private = _transform_key_into_dataobj(
            key_obj, content=content
        )
    elif content.info.filter(tag="type=PrivateKey"):
        is_key = True
        key_obj = objdata.get("key")
        if not key_obj:
            raise ValueError("Cannot transform key to content")

        hashes, public, newdata = _transform_key_into_dataobj(
            key_obj, content=content
        )
        if not newdata:
            raise ValueError()
    else:
        newdata = {
            "cluster": objdata.get("cluster"),
            "references": objdata.get("references"),
            "contentHash": objdata.get("contentHash"),
            "key": key,
            **(objdata.get("value") or {})
        }
    newdata["actions"] = objdata.get("actions")
    func = _update_or_create_content_or_key(
        request, content, newdata, authset, is_key,
        required_keys or []
    )
    with transaction.atomic():
        return func()


def transfer_value(
    content, key=None, url=None, headers=None, transfer=True
):
    _headers = {}
    if key:
        assert not url, "can only specify key or url"
        try:
            _blob = AESGCM(key).decrypt(
                content.value.open("rb").read(),
                base64.b64decode(content.nonce),
                None
            ).split(b'\r\n', 1)
            if len(_blob) == 1:
                url = _blob[0]
            else:
                url = _blob[0]
                _headers.update(
                    BytesParser().parsebytes(_blob[1], headersonly=True)
                )
        except Exception as exc:
            logger.error("Error while decoding url, headers", exc_info=exc)
            return TransferResult.ERROR

    if headers:
        if isinstance(headers, str):
            headers = json.loads(headers)
        _headers.update(headers)

    params, inline_domain = get_requests_params(url)
    # block content while updating file
    q = Q(id=content.id)
    if transfer:
        q &= Q(info__tag="transfer")
    bcontents = Content.objects.filter(
        q
    ).select_for_update()
    with transaction.atomic():
        # 1. lock content, 2. check if content was deleted before updating
        if not bcontents:
            return TransferResult.ERROR
        if inline_domain:
            response = Client().get(
                url,
                Connection="close",
                SERVER_NAME=inline_domain,
                **_headers
            )
            if response.status_code == 404:
                return TransferResult.NOTFOUND
            elif response.status_code != 200:
                return TransferResult.ERROR
            # should be only one nonce
            checknonce = response.get("X-NONCES", "").strip(", ")
            if checknonce != "":
                if len(checknonce) != 20:
                    logger.warning("Invalid nonce (not 13 bytes)")
                    return TransferResult.ERROR
                content.nonce = checknonce
            try:
                with content.value.open("wb") as f:
                    for chunk in response.streaming_content:
                        f.write(chunk)
                if transfer:
                    content.references.filter(group="transfer").delete()
                return TransferResult.SUCCESS
            except Exception as exc:
                logger.error("Error while transferring content", exc_info=exc)
            return TransferResult.ERROR
        else:
            try:
                with requests.get(
                    url,
                    headers={
                        "Connection": "close",
                        **_headers
                    },
                    **params
                ):
                    if response.status_code == 404:
                        return TransferResult.NOTFOUND
                    elif response.status_code != 200:
                        return TransferResult.ERROR
                    # should be only one nonce
                    checknonce = response.get("X-NONCES", "").strip(", ")
                    if checknonce != "":
                        if len(checknonce) != 20:
                            logger.warning("Invalid nonce (not 13 bytes)")
                            return TransferResult.ERROR
                        content.nonce = checknonce
                    with content.value.open("wb") as f:
                        for chunk in response.iter_content(512):
                            f.write(chunk)
                    if transfer:
                        content.references.filter(group="transfer").delete()
                    return TransferResult.SUCCESS
            except Exception as exc:
                logger.error("Error while transferring content", exc_info=exc)
            return TransferResult.ERROR
