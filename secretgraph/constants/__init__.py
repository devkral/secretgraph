import enum

from rdflib import Namespace


class Action(enum.Enum):
    pass


class DeleteRecursive(enum.Enum):
    FALSE = False
    TRUE = True
    NO_GROUP = None


class MetadataOperations(enum.Enum):
    append = "append"
    remove = "remove"
    replace = "replace"


class TransferResult(enum.Enum):
    SUCCESS = "success"
    NOTFOUND = "notfound"
    ERROR = "error"
    FAILED_VERIFICATION = "failed_verification"


SECRETGRAPH = Namespace(
    "https://secretgraph.net/static/schemes/secretgraph/secretgraph#"
)
CLUSTER = Namespace(
    "https://secretgraph.net/static/schemes/secretgraph/cluster#"
)
SIMPLECONTENT = Namespace(
    "https://secretgraph.net/static/schemes/secretgraph/simplecontent#"
)
