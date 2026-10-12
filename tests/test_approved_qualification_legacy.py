"""A stricter current semantic check gives an explicit profile fallback."""
import pytest

from app.domain import approved_qualification as service
from app.knowledge.qualification import QualificationError
from tests.test_approved_qualification import env,ready,clock,propose
from tests.test_applicant_profiles import read
from app.admin.qualification_copy import reasons


@pytest.mark.parametrize('language',['ru','en'])
def test_current_semantic_conflict_returns_explanation_without_changing_history(ready,monkeypatch,language):
    before=read(ready,ready['person'])
    def conflict(self,request):
        raise QualificationError('family_exceeds_applicants')
    monkeypatch.setattr(service.QualificationReview,'evaluate',conflict)
    report=propose(ready)
    assert report['candidate'] is None and report['status']=='specialist_review'
    assert report['reasons']==['individual_profile_answers_conflict']
    assert report['requires_specialist'] and not report['may_quote']
    assert not report['entry_eligibility_evaluated'] and report['visa_required'] is None
    assert report['next_questions']==[]
    report['language']=language
    assert ('несогласованные ответы' if language=='ru' else 'inconsistent answers') in reasons(report)[0]
    assert read(ready,ready['person'])==before
