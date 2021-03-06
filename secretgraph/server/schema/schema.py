from graphene import Field, List, ID, ObjectType, relay
from django.utils.translation import gettext_lazy as _

from .arguments import AuthList
from ..utils.auth import initializeCachedResult
from .definitions import (
    ClusterConnectionField, ContentConnectionField, SecretgraphConfig
)
from .mutations import (
    ClusterMutation, ContentMutation, DeleteContentOrClusterMutation,
    MetadataUpdateMutation, PushContentMutation, RegenerateFlexidMutation,
    ResetDeletionContentOrClusterMutation
)


class SecretgraphObject(ObjectType):
    node = relay.Node.Field()
    config = Field(SecretgraphConfig)
    clusters = ClusterConnectionField()
    contents = ContentConnectionField(
        clusters=List(
            ID, required=False
        )
    )

    def resolve_config(self, info, **kwargs):
        return SecretgraphConfig()


class Query():
    secretgraph = Field(
        SecretgraphObject, authorization=AuthList()
    )

    def resolve_secretgraph(
        self, info, authorization=None, **kwargs
    ):
        initializeCachedResult(
            info.context, authset=authorization
        )
        return SecretgraphObject()


class Mutation():
    updateOrCreateContent = ContentMutation.Field(
        description=_(
            "Supports creation or update of:\n"
            "  public key or key-pair (key): used for further encryption.\n"
            "  content (value): a content encrypted by public key"
        )
    )
    updateOrCreateCluster = ClusterMutation.Field(
        description=_(
            "Create a cluster, optionally initialize with a key-(pair)"
        )
    )
    updateMetadata = MetadataUpdateMutation.Field()
    pushContent = PushContentMutation.Field()
    regenerateFlexid = RegenerateFlexidMutation.Field()
    deleteContentOrCluster = DeleteContentOrClusterMutation.Field()
    resetDeletionContentOrCluster = \
        ResetDeletionContentOrClusterMutation.Field()
