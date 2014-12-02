#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2014 uralbash <root@uralbash.ru>
#
# Distributed under terms of the MIT license.

"""
Logging Exceptions To Your SQLAlchemy Database
"""
import base64
import pickle
from collections import namedtuple
from datetime import datetime
from json import dumps, JSONEncoder

from pyramid.threadlocal import get_current_request
from sqlalchemy import Column, event, ForeignKey
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import relationship
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime, Integer, String, UnicodeText

Base = declarative_base()
ACTIONS = ('INSERT', 'UPDATE', 'CREATE', 'DELETE', 'ALTER')


def _current_user_id_or_none():
    user = None

    request = get_current_request()
    if request:
        user = request.authenticated_userid
    return user or 0


class AuditMixin(object):

    """Abstract mixin wich added field for audit:

       * created_by_id - who create
       * updated_by_id - who last updated
       * created_at - creation date
       * updated_at - date of last update

    Field updated automatically. Who create or update refer to the model of
    User. The user is taken from current session, using the
    pyramid.threadlocal.get_current_request
    """

    @declared_attr
    def created_by_id(cls):
        return Column(Integer,
                      ForeignKey('users.id',
                                 name='fk_%s_created_by_id' % cls.__name__,
                                 use_alter=True,
                                 onupdate="cascade",
                                 ondelete="restrict"),
                      default=_current_user_id_or_none
                      )

    @declared_attr
    def created_by(cls):
        return relationship(
            'User',
            primaryjoin='User.id == %s.created_by_id' % cls.__name__,
            remote_side='User.id'
        )

    @declared_attr
    def updated_by_id(cls):
        return Column(Integer,
                      ForeignKey('users.id',
                                 name='fk_%s_updated_by_id' % cls.__name__,
                                 use_alter=True,
                                 onupdate="cascade",
                                 ondelete="restrict"),
                      default=_current_user_id_or_none,
                      onupdate=_current_user_id_or_none
                      )

    @declared_attr
    def updated_by(cls):
        return relationship(
            'User',
            primaryjoin='User.id == %s.updated_by_id' % cls.__name__,
            remote_side='User.id'
        )

    created_at = Column(DateTime, nullable=False,
                        default=datetime.now())
    updated_at = Column(DateTime, nullable=False,
                        default=datetime.now(),
                        onupdate=datetime.now())


class PythonObjectEncoder(JSONEncoder):

    def default(self, obj):
        if isinstance(obj, (list, dict, str, unicode, int, float, bool,
                            type(None))):
            return JSONEncoder.default(self, obj)
        return {'_python_object': base64.b64encode(pickle.dumps(obj))}


def as_python_object(dct):
    if '_python_object' in dct:
        return pickle.loads(str(dct['_python_object']))
    return dct


def get_value_or_reference(values):

    try:
        val = values[0]
    except Exception:
        val = u''

    if hasattr(val, 'id'):
        return val.id

    return val

FieldChange = namedtuple('FieldChange', 'name old_value new_value')


def get_modified_fields(target):
    """
    returns a list of FieldChange objects, each of this objects will have the
    field name, the old value and the new one
    """
    fields = list()
    for f in target.__table__.c.keys():
        h = get_history(target, f)
        if h.has_changes():
            # FIXME: if it is possible to have h.deleted==[]
            # FIXED: get_value_or_reference tries to handle corner cases like
            # empty changed values and InitMixin subclasses

            old = get_value_or_reference(h.deleted)
            new = get_value_or_reference(h.added)

            fields.append(FieldChange(name=f,
                                      old_value=old,
                                      new_value=new))

    return fields


class LoggableMixin(object):

    """
    This mixin should be able to track creation, update and removal
    of models that extends it
    """
    @staticmethod
    def log_create(mapper, connection, target):
        args = dumps(target.__dict__, cls=PythonObjectEncoder)
        log = Log.__table__.insert().values(
            logger='LoggableMixin',
            level='INFO',
            msg='Create object',
            args=args,
            user_id=str(_current_user_id_or_none()),
        )
        connection.execute(log)

    @staticmethod
    def log_delete(mapper, connection, target):
        args = dumps(target.__dict__, cls=PythonObjectEncoder)
        log = Log.__table__.insert().values(
            logger='LoggableMixin',
            level='INFO',
            msg='Delete object',
            args=args,
            user_id=str(_current_user_id_or_none()),
        )
        connection.execute(log)

    @staticmethod
    def log_update(mapper, connection, target):

        fields = get_modified_fields(target)
        args = {}

        for f in fields:
            args[f.name] = {
                'old_value': f.old_value,
                'new_value': f.new_value
            }
        log = Log.__table__.insert().values(
            logger='LoggableMixin',
            level='INFO',
            msg='Update object',
            args=str(args),
            user_id=str(_current_user_id_or_none()),
        )
        connection.execute(log)

    @classmethod
    def __declare_last__(cls):
        event.listen(cls, 'after_insert', cls.log_create)
        event.listen(cls, 'after_update', cls.log_update)
        event.listen(cls, 'after_delete', cls.log_delete)


class Log(Base):

    """  http://pyramid-cookbook.readthedocs.org/en/latest/logging/sqlalchemy_logger.html
    """
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)  # auto incrementing
    user_id = Column(Integer)               # user id
    logger = Column(String)                 # the name of the logger. (e.g. myapp.views)
    level = Column(String)                  # info, debug, or error?
    trace = Column(String)                  # the full traceback printout
    msg = Column(UnicodeText)               # any custom log you may have included
    args = Column(UnicodeText)              # the name of the logger. (e.g. myapp.views)
    created_at = Column(DateTime,           # the current timestamp
                        default=func.now())

    def __init__(self, logger=None, level=None, trace=None, msg=None,
                 user=None, args=None):
        self.user_id = user
        self.logger = logger
        self.level = level
        self.trace = trace
        self.msg = msg
        self.args = args

    def __unicode__(self):
        return self.__repr__()

    def __repr__(self):
        if self.created_at:
            return "<Log: {0} - {1}>".format(
                self.created_at.strftime('%Y-%m-%d %H:%M:%S'), self.msg[:50])
        return self.msg

    # SACRUD
    sacrud_detail_col = [('', (logger, level, trace, msg, args)), ]


def after_cursor_execute(conn, cursor, statement,
                         parameters, context, executemany):
    if any(item in statement for item in ACTIONS)\
            and Log.__tablename__ not in statement:
        log = Log.__table__.insert().values(
            logger=__name__,
            level='INFO',
            msg=statement,
            args=str(parameters),
            user_id=str(_current_user_id_or_none()),
        )
        conn.execute(log)
