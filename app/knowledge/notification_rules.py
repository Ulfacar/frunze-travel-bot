"""Bounded typed manual inputs with retained, explicitly selected renderers."""
from copy import deepcopy
import json
import re

from app.knowledge import template_renderer_v1

VERSION='kg-notification-renderer/1'
RENDERERS={'kg-notification-renderer/1':template_renderer_v1}
MAX_INPUT_BYTES=16384


class NotificationInvalid(ValueError):pass


def fail(code='invalid_notification_input'):raise NotificationInvalid(code)


def request(value):
    if type(value) is not dict or set(value)!={'template_id','values'}:fail()
    if type(value['template_id']) is not str or not re.fullmatch(r'KG\.TPL\.A[0-9]{2}',value['template_id']):fail()
    values=value['values']
    if type(values) is not dict or len(values)>32:fail()
    for key,item in values.items():
        if type(key) is not str or not re.fullmatch('p[0-9]{2}',key):fail()
        if type(item) is dict:
            if set(item)!={'amount','currency'} or any(type(v) is not str or len(v)>32 for v in item.values()):fail()
        elif type(item) is str:
            if len(item)>500:fail()
        elif type(item) is int:
            if not 1<=item<=36600:fail()
        else:fail()
    try:
        if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'))>MAX_INPUT_BYTES:fail()
    except (ValueError,TypeError,UnicodeError):fail()
    return deepcopy(value)


def renderer(version):
    if type(version) is not str or version not in RENDERERS:fail('notification_renderer_unavailable')
    return RENDERERS[version]


def catalog(version=None):
    engine=renderer(VERSION if version is None else version)
    try:return engine.load_catalog()
    except (ValueError,OSError):fail('notification_catalog_unavailable')


def render(parameters,*,version):
    parameters=request(parameters);engine=renderer(version)
    try:
        result=engine.preview(catalog(version),template_id=parameters['template_id'],values=parameters['values'])
    except ValueError as exc:fail(str(exc))
    result.update(renderer_version=version,input_provenance='manual_unverified',status='saved_draft_content')
    return result
