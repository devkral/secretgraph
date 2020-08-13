
__all__ = [
    "transform_tags", "extract_key_hashes", "transform_references",
    "update_metadata_fn"
]

import logging
import re
from contextlib import nullcontext

from django.db.models import OuterRef, Q, Subquery
from graphql_relay import from_global_id

from ....constants import MetadataOperations
from ....utils.auth import initializeCachedResult
from ....utils.misc import hash_object
from ...models import Content, ContentReference, ContentTag

logger = logging.getLogger(__name__)

len_default_hash = len(hash_object(b""))

denied_remove_filter = re.compile(
    "^(?:id|state|type)=?"
)


def extract_key_hashes(tags):
    key_hashes = set()
    content_type = None
    for tag in tags:
        if isinstance(tag, ContentTag):
            tag = tag.tag
        splitted_tag = tag.split("=", 1)
        if splitted_tag[0] == "key_hash":
            if len_default_hash == len(splitted_tag[1]):
                key_hashes.add(splitted_tag[1])
        elif splitted_tag[0] == "type":
            content_type = splitted_tag[1]
    return key_hashes, content_type


def transform_tags(tags, oldtags=None, operation=MetadataOperations.append):
    newtags = {}
    newtags_set = set()
    key_hashes = set()
    tags = tags or []
    oldtags = oldtags or []
    operation = operation or MetadataOperations.append
    new_had_keyhash = False
    if operation == MetadataOperations.remove and oldtags:
        tags = filter(
            lambda x: not denied_remove_filter.match(x),
            tags
        )
        remove_filter = re.compile(
            r"^(?:%s)" % "|".join(map(
                re.escape,
                tags
            ))
        )
        tags = filter(
            lambda x: not remove_filter.match(x),
            oldtags
        )
    for tag in tags:
        splitted_tag = tag.split("=", 1)
        if splitted_tag[0] == "id":
            logger.warning("id is an invalid tag (autogenerated)")
            continue
        if splitted_tag[0] == "state":
            if newtags.get("state"):
                raise ValueError("state=<foo> is a unique tag")
            elif len(splitted_tag) == 1:
                raise ValueError("state should be tag not flag")
        elif splitted_tag[0] == "type":
            if newtags.get("type"):
                raise ValueError("type=<foo> is a unique tag")
            elif len(splitted_tag) == 1:
                raise ValueError("type should be tag not flag")
        elif splitted_tag[0] == "key_hash":
            if len(splitted_tag) == 1:
                raise ValueError("key_hash should be tag not flag")
            new_had_keyhash = True
            if len_default_hash == len(splitted_tag[1]):
                key_hashes.add(splitted_tag[1])
        if len(tag) > 8000:
            raise ValueError("Tag too big")
        if len(splitted_tag) == 2:
            s = newtags.setdefault(splitted_tag[0], set())
            if not isinstance(s, set):
                raise ValueError("Tag and Flag name collision")
            s.add(splitted_tag[1])
        elif newtags.setdefault(splitted_tag[0], None) is not None:
            raise ValueError("Tag and Flag name collision")
        newtags_set.add(splitted_tag[0])

    if operation != MetadataOperations.remove and oldtags:
        for tag in oldtags:
            splitted_tag = tag.split("=", 1)
            if splitted_tag[0] == "id":
                continue
            if splitted_tag[0] == "state":
                if newtags.get("state"):
                    continue
            elif splitted_tag[0] == "type":
                t = newtags.get("type")
                if t and splitted_tag[1] not in t:
                    raise ValueError("Cannot change type")
                elif t:
                    continue
            elif splitted_tag[0] == "key_hash":
                if operation == MetadataOperations.replace and new_had_keyhash:
                    continue
                if len_default_hash == len(splitted_tag[1]):
                    key_hashes.add(splitted_tag[1])

            if len(splitted_tag) == 2:
                if (
                    operation == MetadataOperations.append or
                    splitted_tag[0] not in newtags_set
                ):
                    s = newtags.setdefault(splitted_tag[0], set())
                    if not isinstance(s, set):
                        continue
                    s.add(splitted_tag[1])
            elif newtags.setdefault(splitted_tag[0], None) is not None:
                pass

    if (
        newtags.get("content_type") == {"PrivateKey"} and
        not newtags.get("key")
    ):
        raise ValueError("PrivateKey has no key=<foo> tag")
    return newtags, key_hashes


def transform_references(
    content, references, key_hashes_tags, allowed_targets,
    no_final_refs=False
):
    # no_final_refs final_references => None
    final_references = None if no_final_refs else []
    sig_target_hashes = set()
    encrypt_target_hashes = set()
    deduplicate = set()
    for ref in references or []:
        if isinstance(ref, ContentReference):
            refob = ref
            if not allowed_targets.filter(
                id=refob.target_id, markForDestruction=None
            ).exists():
                continue
        else:
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

                targetob = allowed_targets.filter(
                    q, markForDestruction=None
                ).first()
            if not targetob:
                continue
            refob = ContentReference(
                source=content,
                target=targetob,
                group=ref.get("group") or "",
                extra=ref.get("extra") or ""
            )
        # first extra tag in same group  with same target wins
        if (refob.group, refob.target.id) in deduplicate:
            continue
        deduplicate.add((refob.group, refob.target.id))
        if len(refob.extra) > 8000:
            raise ValueError("Extra tag too big")
        if refob.group == "signature":
            refob.deleteRecursive = None
            sig_target_hashes.add(targetob.contentHash)
        if refob.group in {"key", "transfer"}:
            refob.deleteRecursive = None
            if refob.group == "key":
                encrypt_target_hashes.add(targetob.contentHash)
            if targetob.contentHash not in key_hashes_tags:
                raise ValueError("Key hash not found in tags")
        if not no_final_refs:
            final_references.append(refob)
    return final_references, encrypt_target_hashes, sig_target_hashes


def update_metadata_fn(
    request, content, *,
    tags=None, references=None, operation=MetadataOperations.append,
    authset=None, required_keys=None
):
    operation = operation or MetadataOperations.append
    final_tags = None
    remove_tags_q = ~Q(tag__startswith="id=")
    remove_refs_q = Q()
    if tags:
        oldtags = content.tags.values_list("tag", flat=True)
        tags_dict, key_hashes_tags = transform_tags(
            tags,
            oldtags,
            operation
        )
        content_state = next(iter(tags_dict.get("state", {None})))
        content_type = next(iter(tags_dict.get("type", {None})))
        if content_type in {"PrivateKey", "PublicKey"}:
            if content_state not in {"public", "internal"}:
                raise ValueError(
                    "%s is an invalid state for key", content_state
                )
        else:
            if content_type == "Config" and content_state != "internal":
                raise ValueError(
                    "%s is an invalid state for Config", content_type
                )
            elif content_state not in {
                "draft", "public", "internal"
            }:
                raise ValueError(
                    "%s is an invalid state for content", content_state
                )

        if operation in {
            MetadataOperations.append, MetadataOperations.replace
        }:
            final_tags = []
            for prefix, val in tags_dict.items():
                if not val:
                    remove_tags_q |= Q(tag__startswith=prefix)
                    final_tags.append(ContentTag(
                        content=content,
                        tag=prefix
                    ))
                else:
                    for subval in val:
                        composed = "%s=%s" % (prefix, subval)
                        remove_tags_q |= Q(tag__startswith=composed)
                        final_tags.append(ContentTag(
                            content=content,
                            tag=composed
                        ))
        else:
            for prefix, val in tags_dict.items():
                if not val:
                    remove_tags_q &= ~Q(tag__startswith=prefix)
                else:
                    for subval in val:
                        composed = "%s=%s" % (prefix, subval)
                        remove_tags_q &= ~Q(tag__startswith=composed)
    else:
        kl = content.tags.filter(
            Q(tag__startswith="key_hash=") |
            Q(tag__startswith="type=")
        ).values_list("tag", flat=True)
        key_hashes_tags, content_type = extract_key_hashes(kl)

    if references is None:
        _refs = content.references.all()
    elif operation in {MetadataOperations.remove, MetadataOperations.replace}:
        _refs = []
        if MetadataOperations.replace:
            _refs = references
        remrefs = set(map(
            lambda x: (x["group"], x["target"]),
            references
        ))
        for ref in content.references.all():
            if (ref.group, None) in remrefs:
                remove_refs_q |= Q(
                    id=ref.id
                )
                continue
            elif (ref.group, ref.target_id) in remrefs:
                remove_refs_q |= Q(
                    id=ref.id
                )
                continue
            elif (ref.group, ref.target.contentHash) in remrefs:
                remove_refs_q |= Q(
                    id=ref.id
                )
                continue
            _refs.append(ref)
    elif MetadataOperations.append:
        # prefer old extra values, no problem with crashing as ignore_conflict
        _refs = [
            *content.references.all(),
            *references
        ]
    # no_final_refs => final_references = None
    final_references, key_hashes_ref, verifiers_ref = \
        transform_references(
            content,
            _refs,
            key_hashes_tags,
            initializeCachedResult(
                request, authset=authset
            )["Content"]["objects"],
            no_final_refs=references is None
        )

    if required_keys and required_keys.isdisjoint(verifiers_ref):
        raise ValueError("Not signed by required keys")
    if (
        content_type not in {"PrivateKey", "PublicKey"} and
        len(key_hashes_ref) < 1
    ):
        raise ValueError(
            ">=1 key references required for content"
        )

    def save_fn(context=nullcontext):
        if callable(context):
            context = context()
        with context:
            if final_tags is not None:
                if operation in {
                    MetadataOperations.remove, MetadataOperations.replace
                }:
                    content.tags.filter(remove_tags_q).delete()
                if operation in {
                    MetadataOperations.append, MetadataOperations.replace
                }:
                    ContentTag.objects.bulk_create(
                        final_tags, ignore_conflicts=True
                    )
            if final_references is not None:
                if operation in {
                    MetadataOperations.remove, MetadataOperations.replace
                }:
                    content.references.filter(remove_refs_q).delete()
                if operation in {
                    MetadataOperations.append, MetadataOperations.replace
                }:
                    ContentReference.objects.bulk_create(
                        final_references, ignore_conflicts=True
                    )
            return content
    return save_fn
