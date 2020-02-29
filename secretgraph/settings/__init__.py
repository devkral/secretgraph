
"""
Django settings for secretgraph project.
"""

import os

import certifi
from cryptography.hazmat.primitives import hashes
from django.utils.translation import gettext_lazy as _

DEBUG = os.environ.get("DEBUG") == "true"


# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


GRAPHENE = {
    'SCHEMA': 'secretgraph.schema.schema',
    'SCHEMA_OUTPUT': 'data/schema.json',  # defaults to schema.json,
    'SCHEMA_INDENT': 2,
    'MIDDLEWARE': []
}

if DEBUG:
    GRAPHENE['MIDDLEWARE'].append(
        'graphene_django.debug.DjangoDebugMiddleware'
    )

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.11/howto/deployment/checklist/


ALLOWED_HOSTS = []

FILE_UPLOAD_HANDLERS = [
    'django.core.files.uploadhandler.MemoryFileUploadHandler',
    "spkcspider.apps.spider.functions.LimitedTemporaryFileUploadHandler",
]


# Application definition

INSTALLED_APPS = [
    'widget_tweaks',
    'spkcspider.apps.spider_accounts',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',  # for flatpages
    'django.contrib.flatpages',
    'django.contrib.sitemaps',
    'spkcspider.apps.spider',
]
try:
    import django_extensions  # noqa: F401
    INSTALLED_APPS.append('django_extensions')
except ImportError:
    pass


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'spkcspider.apps.spider.middleware.TokenUserMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.contrib.flatpages.middleware.FlatpageFallbackMiddleware',
]

ROOT_URLCONF = 'spkcspider.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'spkcspider.apps.spider.context_processors.settings',
                'django.template.context_processors.i18n',
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]
WSGI_APPLICATION = 'spkcspider.wsgi.application'

# Password validation
# https://docs.djangoproject.com/en/1.11/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',  # noqa: E501
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',  # noqa: E501
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',  # noqa: E501
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',  # noqa: E501
    },
]


# Internationalization
# https://docs.djangoproject.com/en/1.11/topics/i18n/

LANGUAGE_CODE = 'en'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


STATICFILES_DIRS = [
    # add node_modules as node_modules under static
    ("node_modules", "node_modules")
]

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.11/howto/static-files/


STATIC_ROOT = 'static/'
STATIC_URL = '/static/'

MEDIA_ROOT = 'media/'
MEDIA_URL = '/media/'


CAPTCHA_CHALLENGE_FUNCT = 'captcha.helpers.math_challenge'
CAPTCHA_FONT_SIZE = 40

LOGIN_URL = "auth:login"
LOGIN_REDIRECT_URL = "auth:profile"
LOGOUT_REDIRECT_URL = "home"

AUTH_USER_MODEL = 'spider_accounts.SpiderUser'
# uses cryptography, can automatically determinate size
SPIDER_HASH_ALGORITHM = hashes.SHA512()
SPIDER_MIN_STRENGTH_EVELATION = 2
# change size of request token.
# Note: should be high to prevent token exhaustion
# TOKEN_SIZE = 30
# Change size of token for files (should be >=TOKEN_SIZE),
#  defaults to TOKEN_SIZE
# FILE_TOKEN_SIZE
# OPEN_FOR_REGISTRATION = True # allow registration
# ALLOW_USERNAME_CHANGE = True # allow users changing their username

## Default static token size (!=TOKEN_SIZE) # noqa: E266
# SPIDER_INITIAL_STATIC_TOKEN_SIZE

## captcha field names (REQUIRED) # noqa: E266
SPIDER_CAPTCHA_FIELD_NAME = "sunglasses"

## Update dynamic content, ... after migrations, default=true  # noqa: E266
# disable when importing backup
# ease deploy
UPDATE_DYNAMIC_AFTER_MIGRATION = True

# controls inlining of requests calls (default: None)
# can take a function with specification func(url) -> bool
#
#   by faking requests calls on urls which are internal
#   deadlocking hazards are avoided and the speed is increased
#   so it is really recommended to not set this setting on False
# SPIDER_INLINE = False

## extensions of images (used in file_filets)  # noqa: E266
# SPIDER_IMAGE_EXTENSIONS
## extensions of media (used in file_filets)  # noqa: E266
# SPIDER_MEDIA_EXTENSIONS

## embeddding function for files in graph, for e.g. linking  # noqa: E266
# SPIDER_FILE_EMBED_FUNC

## validator function for url requests  # noqa: E266
# SPIDER_URL_VALIDATOR

## Enable captchas  # noqa: E266
# INSTALLED_APPS.append('captcha')
# USE_CAPTCHAS = True

## Approval function for allowing dangerous self and travel protections  # noqa: E266, E501
##   Note: return False means don't allow and None ask admin  # noqa: E266
# SPIDER_DANGEROUS_APPROVE

# DIRECT_FILE_DOWNLOAD = True

# SPIDER_CONTENTVARIANT_FILTER

# SPIDER_TAG_VERIFIER_VALIDATOR
# SPIDER_TAG_VERIFY_REQUEST_VALIDATOR

# SPIDER_ANCHOR_DOMAIN
# SPIDER_ANCHOR_SCHEME
# SPIDER_COMPONENTS_DELETION_PERIODS
# SPIDER_CONTENTS_DEFAULT_DELETION_PERIOD
# SPIDER_RATELIMIT_FUNC
## Enable direct file downloads (handled by webserver)  # noqa: E266
# disadvantage: blocking access requires file name change
# FILE_DIRECT_DOWNLOAD
# FILE_FILET_DIR
# FILE_FILET_SALT_SIZE
# SPIDER_UPLOAD_FILTER
# SPIDER_GET_QUOTA
# SPIDER_MAX_FILE_SIZE
# SPIDER_MAX_FILE_SIZE_STAFF
# SPIDER_USER_QUOTA_LOCAL
# SPIDER_USER_QUOTA_REMOTE
## in units  # noqa: E266
# SPIDER_USER_QUOTA_USERCOMPONENTS

# unbreak old links after switch to a new machine friendly url layout
SPIDER_LEGACY_REDIRECT = True

##  Use subpath to create ids for identifiers # noqa: E266
# SPIDER_ID_USE_SUBPATH

# usercomponents created with user
SPIDER_DEFAULT_COMPONENTS = {
    "home": {
        "public": False,
        "features": ["Persistence", "WebConfig"]
    },
    "public": {
        "public": True,
        "features": []
    },
}

## Default description  # noqa: E266
SPIDER_DESCRIPTION = "A spkcspider instance for your personal data."

SPIDER_BLACKLISTED_MODULES = []

# maximal domain_mode activation per usercomponent/domain
SPIDER_DOMAIN_UPDATE_RATE = "10/m"
# maximal error rate for a domain before blocking requests
SPIDER_DOMAIN_ERROR_RATE = "10/10m"
# max description length (stripped)
SPIDER_MAX_DESCRIPTION_LENGTH = 200
# how many user components/contents per page
SPIDER_OBJECTS_PER_PAGE = 25
# how many raw/serialized results per page?
SPIDER_SERIALIZED_PER_PAGE = 50
# max depth of references used in embed
#   should be >=5, allows 4 levels depth in contents+link to it
SPIDER_MAX_EMBED_DEPTH = 5
# how many search parameters are allowed
SPIDER_MAX_SEARCH_PARAMETERS = 30
# licences for media
SPIDER_LICENSE_CHOICES = {
    "other": {
        "url": ""
    },
    "pd": {
        "name": _("Public Domain/CC0"),
        "url":
            "https://creativecommons.org/publicdomain/zero/1.0/legalcode"
    },
    "CC BY": {
        "url": "https://creativecommons.org/licenses/by/4.0/legalcode"
    },
    "CC BY-SA": {
        "url": "https://creativecommons.org/licenses/by-sa/4.0/legalcode"
    },
    "CC BY-ND": {
        "url": "https://creativecommons.org/licenses/by-nd/4.0/legalcode"
    },
    "CC BY-NC": {
        "url": "https://creativecommons.org/licenses/by-nc/4.0/legalcode"
    },
    "CC BY-NC-SA": {
        "url": "https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode"
    },
    "CC BY-NC-ND": {
        "url": "https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode"
    },
}
SPIDER_DEFAULT_LICENSE_FILE = "CC BY"

# licences for text (default: file licenses are used)
# SPIDER_LICENSE_CHOICES_TEXT
# SPIDER_DEFAULT_LICENSE_TEXT

# requests parameter overwrites
# * "hostname.foo": parameter for specific domain
# * "".foo": parameter for a tld
# * b"default": default parameters for request
# why binary? Because it cannot clash with a "default" host this way
# hierarchy: host > tld > b"default"
SPIDER_REQUEST_KWARGS_MAP = {
    b"default": {
        "verify": certifi.where(),
        "timeout": 3,
        "proxies": {}
    },
    # example for usage with tor (requires requests[socks])
    # ".onion": {
    #     "timeout": 10,
    #     "proxies": {
    #        'http': 'socks5://localhost:9050',
    #        'https': 'socks5://localhost:9050'
    #     }
    # }
    # example for a slow domain
    # "veryslow.example": {
    #     "timeout": 60,
    #     "proxies": {}
    # }
}


# for sites
SITE_ID = 1
