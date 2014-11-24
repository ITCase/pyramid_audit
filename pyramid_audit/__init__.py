#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2014 uralbash <root@uralbash.ru>
#
# Distributed under terms of the MIT license.

"""
Logger

It based on:
    * http://pyramid-cookbook.readthedocs.org/en/latest/logging/sqlalchemy_logger.html
    * http://docs.sqlalchemy.org/en/latest/orm/events.html
"""
from sqlalchemy.engine import Engine
from sqlalchemy.event import listen

from .models import after_cursor_execute


def includeme(config):
    listen(Engine, "after_cursor_execute", after_cursor_execute)
