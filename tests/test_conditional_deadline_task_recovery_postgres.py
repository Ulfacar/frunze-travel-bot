import asyncio
import json
from pathlib import Path

from tests.test_entry_process_postgres import template,env
from tests.test_conditional_deadlines import clock
from tests import test_conditional_deadline_recovery_postgres as backup
from app.domain import entry_deadline_tasks as tasks
from app.config import settings


def test_actual_copy_preserves_enabled_task_and_clears_it_after_restore(env,tmp_path,monkeypatch):
    original=backup.record; task_id=[]; assertions=[]
    def wrapped(target,command):
        receipt=original(target,command)
        options={k:v for k,v in target['conditional_args'].items() if k not in ('authority','applicant_id')}
        if not task_id:
            monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[target['conditional_args']['authority'].document])
            bound=asyncio.run(tasks.reconcile_deadline_task(target['engine'],**options,enable=True))
            assert bound['task']['status']=='planned'
            task_id.append(bound['task']['id'])
        if command['operation']['action']=='conditional_clear':
            current=asyncio.run(tasks.read_deadline_task(target['engine'],**options))
            assert current['current']['task']['id']==task_id[0] and current['current']['task']['status']=='cancelled'
            assert current['due_on'] is None
            assertions.append(True)
        return receipt
    monkeypatch.setattr(backup,'record',wrapped)
    backup.test_conditional_binary_copy_recovery_preserves_evidence_retry_and_next_clear(env,tmp_path)
    assert assertions==[True]
    report=json.loads(Path('runs/conditional-deadline-recovery.json').read_text('utf8'))
    assert report['table_counts']['entry_conditional_evidence']==1
    assert report['table_counts']['calendar_tasks']>=1
    report.update(enabled_task_restored=True,same_task_cancelled_on_next_clear=True)
    Path('runs/audit-conditional-recovery.json').write_text(json.dumps(report,indent=2)+'\n','utf8')
