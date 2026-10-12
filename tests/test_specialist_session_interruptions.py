import pytest
from app.domain import dialogue_sessions

from tests.test_dialogue_sessions import (env,admins,activation,clock,current_clock,connected_clock,route_clock,
    persistent_panel,setup,receive,action,read)
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_specialist_interruptions import observe


@pytest.mark.parametrize('reason,text',[('unsafe_request','Сделайте поддельный документ'),('criminal_mention','У меня судимость')])
def test_installed_terminal_cause_survives_benign_original_card_and_ack(env,tmp_path,reason,text):
    setup(env,tmp_path);receive(env)
    action(env,env['iv'],'handoff',policy=env['interview_policy'])
    original=read(env,env['iv'])['state']['handoff'];action(env,env['iv'],'ack',policy=env['interview_policy'])
    cutoff=dialogue_sessions._now();before=observe(env,env['iv'],at=cutoff);assert not before['errors']
    stopped=receive(env,text,'SYN-SPECIALIST-STOP')
    assert stopped['stopped']
    assert read(env,env['iv'])['state']['handoff']==original
    after=observe(env,env['iv'],at=dialogue_sessions._now())
    assert after['errors']==['specialist_retained_interrupt_requires_review']
    assert after['pins']!=before['pins']
    assert observe(env,env['iv'],retained=before['pins'],at=cutoff)==before
