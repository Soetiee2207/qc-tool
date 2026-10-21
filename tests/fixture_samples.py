"""Offline source/fixture examples shared by retained data and runtime tests."""
import json

BASE = 'https://fixture.test'
ACTION = 'Nhập email và mật khẩu đúng; bấm Đăng nhập'
HAPPY = 'Đăng nhập thành công; URL chuyển tới /; POST /api/auth/login trả 200 với success=true'


def flows(*ids):
    return {'flow':[{'id':i,'source_file':'flows.md','source_line':8,
        'steps':[{'action':'Open /login','expected':'URL /login'}]} for i in ids or ('FLOW-1',)]}


def note(req, field):
    return '[source-clause] ' + json.dumps({'requirement_id':req['id'],'field':field,'text':req[field]})
