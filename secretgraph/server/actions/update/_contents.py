__all__ = [
    "create_content_func", "update_content_func", "create_key_func",
    "transform_tags"
]


import base64
import logging
from itertools import chain

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_der_public_key
from django.core.files.base import ContentFile, File
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from graphql_relay import from_global_id
from rdflib import Graph

from ....utils.auth import id_to_result, initializeCachedResult
from ....utils.encryption import default_padding, encrypt_into_file
from ....constants import TagsOperations
from ....utils.misc import (
    calculate_hashes, get_secrets, hash_object, refresh_fields
)
from ...models import Cluster, Content, ContentReference, ContentTag
from ._actions import create_actions_func

logger = logging.getLogger(__name__)

len_default_hash = len(hash_object(b""))


def transform_tags(
    content, tags, oldtags=None, operation=TagsOperations.replace
):
    tags = []
    key_hashes = set()
    content_type = None
    content_state = None
    for i in set(tags or []):
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
            raise ValueError("Tag too big")
        tags.append(ContentTag(content=content, tag=i))
    return tags, key_hashes, content_type, content_state or "default"


def _transform_references(content, objdata, key_hashes_tags, allowed_contents):
    final_references = []
    verifiers_ref = set()
    key_hashes_ref = set()
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
                _refs = Subquery(
                    ContentTag.objects.filter(
                        # for correct chaining
                        tag="type=PublicKey",
                        content_id=OuterRef("pk"),
                        content__tags__tag=f"key_hash={ref['target']}"
                    ).values("pk")
                )
                # the direct way doesn't work
                # subquery is necessary for chaining operations correctly
                q = (
                    Q(tags__tag=f"id={ref['target']}") |
                    Q(tags__in=_refs)
                )

            targetob = allowed_contents.filter(
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
        if refob.group == "signature":
            refob.deleteRecursive = None
            verifiers_ref.add(targetob.contentHash)
        if refob.group in {"key", "transfer"}:
            refob.deleteRecursive = None
            if refob.group == "key":
                key_hashes_ref.add(targetob.contentHash)
            if targetob.contentHash not in key_hashes_tags:
                raise ValueError("Key hash not found in tags")
        final_references.append(refob)
    return final_references, key_hashes_ref, verifiers_ref


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
    hashes_tags = tuple(map(
        lambda x: f"key_hash={x}", hashes
    ))

    return (
        hashes,
        {
            "nonce": b"",
            "value": key_obj["publicKey"],
            "tags": chain(
                ["type=PublicKey"],
                hashes_tags,
                key_obj.get("publicTags") or []
            ),
            "contentHash": hashes[0]
        },
        {
            "nonce": key_obj["nonce"],
            "value": key_obj["privateKey"],
            "tags": chain(
                ["type=PrivateKey"],
                hashes_tags,
                key_obj.get("privateTags") or []
            ),
            "contentHash": None
        } if key_obj.get("privateKey") else None
    )


def _update_or_create_content_or_key(
    request, content, objdata, authset, is_key, required_keys
):
    if isinstance(objdata.get("cluster"), str):
        objdata["cluster"] = id_to_result(
            request,
            objdata["cluster"],
            Cluster,
            scope="update",
            authset=authset
        )["objects"].filter(markForDestruction=None).first()
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
                objdata["nonce"] = base64.b64encode(checknonce).decode("ascii")
            else:
                checknonce = base64.b64decode(objdata["nonce"])
        except Exception:
            # no nonce == trigger encryption
            objdata["value"], objdata["nonce"], objdata["key"] = \
                encrypt_into_file(
                    objdata["value"],
                    key=objdata.get("key") or None
                )
            objdata["nonce"] = \
                base64.b64encode(objdata["nonce"]).decode("ascii")
        # is public key? then ignore nonce checks
        if not is_key or not objdata.get("contentHash"):
            if len(checknonce) != 13:
                raise ValueError("invalid nonce size")
            if checknonce.count(b"\0") == len(checknonce):
                raise ValueError("weak nonce")
        assert isinstance(objdata["nonce"], str), "nonce should be here base64 astring, %s" % type(objdata["nonce"])  # noqa E502
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
        save_func_value = content.save

    final_tags = None
    if objdata.get("tags") is not None:
        final_tags, key_hashes_tags, content_type, content_state = \
            transform_tags(content, objdata.get("tags"))
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
        key_hashes_tags = set()
        content_type = None
        content_state = None

    # cannot change because of special key transformation
    chash = objdata.get("contentHash")
    if chash is not None:
        if len(chash) not in (0, len_default_hash):
            raise ValueError("Invalid hashing algorithm used for contentHash")
        if chash == "":
            content.contentHash = None
        else:
            content.contentHash = chash

    final_references = None
    key_hashes_ref = set()
    verifiers_ref = set()
    if objdata.get("references") is not None:
        final_references, key_hashes_ref, verifiers_ref = \
            _transform_references(
                content, objdata, key_hashes_tags, initializeCachedResult(
                    request, authset=authset
                )["Content"]["objects"]
            )
        if required_keys and required_keys.isdisjoint(verifiers_ref):
            raise ValueError("Not signed by required keys")
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
                tags__tag="type=PublicKey"
            )

            if required_keys:
                _refs = Subquery(
                    ContentTag.objects.filter(
                        # for correct chaining
                        tag="type=PublicKey",
                        content_id=OuterRef("pk"),
                        content__tags__tag__in=map(
                            lambda x: f"key_hash={x}",
                            required_keys
                        )
                    ).values("pk")
                )
                default_keys |= Content.objects.filter(
                    tags__in=_refs
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
                key_hashes_tags.add(keyob.contentHash)
                final_tags.append(ContentTag(
                    tag=f"key_hash={keyob.contentHash}"
                ))
    if final_tags is not None:
        if content_type == "PrivateKey" and len(key_hashes_tags) < 1:
            raise ValueError(
                "requires hash of decryption key as key_hash tag"
            )
        elif (
            content_type == "PublicKey" and
            content.contentHash not in key_hashes_tags
        ):
            raise ValueError(
                ">=1 key_hash info tags required for PublicKey (own hash)"
            )
        elif not key_hashes_tags.issuperset(required_keys):
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
        if final_tags is not None:
            if create:
                ContentTag.objects.bulk_create(refresh_fields(
                    final_tags, "content"
                ))
            else:
                # simply ignore id=, can only be changed in regenerateFlexid
                content.tags.exclude(
                    Q(tag__startswith="id=")
                ).delete()
                ContentTag.objects.bulk_create(
                    final_tags, "content"
                )
            if content_state != "default":
                content.tags.create(tag="state=%s" % content_state)

        # create id tag after object was created or update it
        content.tags.update_or_create(
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
        if final_tags is not None and content_state == "default":
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
                        key_hashes_tags
                    ):
                        content.tags.create(tag="state=public")
                    else:
                        content.tags.create(tag="state=internal")
                elif content_type == "Config":
                    content.tags.create(tag="state=internal")
                else:
                    content.tags.create(tag="state=draft")
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
        objdata["cluster"] = id_to_result(
            request,
            objdata["cluster"],
            Cluster,
            authset=authset
        )["objects"].filter(markForDestruction=None).first()
    if not objdata.get("cluster"):
        raise ValueError("No cluster")

    hashes, public, private = _transform_key_into_dataobj(key_obj)
    publickey_content = None
    if objdata["cluster"].id:
        publickey_content = Content.objects.filter(
            cluster=objdata["cluster"],
            tags__tag="type=PublicKey",
            tags__tag__in=map(lambda x: f"key_hash={x}", hashes)
        ).first()
    publickey_content = \
        publickey_content or Content(cluster=objdata["cluster"])
    if key:
        private["tags"] = chain(
            private["tags"],
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


def create_content_func(
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
        _save_func = create_key_func(
            request, objdata, authset=authset
        )

        def save_func():
            with transaction.atomic():
                return _save_func()[0]
    else:
        newdata = {
            "cluster": objdata.get("cluster"),
            "references": objdata.get("references"),
            "contentHash": objdata.get("contentHash"),
            "tags": value_obj.get("tags"),
            "actions": objdata.get("actions"),
            "key": key,
            **value_obj
        }
        content_obj = Content()
        _save_func = _update_or_create_content_or_key(
            request, content_obj, newdata, authset, False,
            required_keys or []
        )

        def save_func():
            with transaction.atomic():
                return _save_func()
    return save_func


def update_content_func(
    request, content, objdata, key=None, authset=None,
    required_keys=None
):
    assert content.id
    is_key = False
    # TODO: maybe allow updating both keys (only tags)
    if content.tags.filter(tag="type=PublicKey"):
        is_key = True
        required_keys = []
        key_obj = objdata.get("key")
        if not key_obj:
            raise ValueError("Cannot transform key to content")

        hashes, newdata, _private = _transform_key_into_dataobj(
            key_obj, content=content
        )
    elif content.tags.filter(tag="type=PrivateKey"):
        is_key = True
        key_obj = objdata.get("key")
        if not key_obj:
            raise ValueError("Cannot transform key to content")

        hashes, _public, newdata = _transform_key_into_dataobj(
            key_obj, content=content
        )
        if not newdata:
            raise ValueError("No data for private key")
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

    def save_func():
        with transaction.atomic():
            return func()
    return save_func
