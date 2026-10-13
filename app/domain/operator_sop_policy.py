"""Default-empty delegation for a specific operator-selected source duty."""
from dataclasses import dataclass
import json

from app.domain import operator_sop_rules as rules
from app.domain.entry_anchor_rules import day,shape,text
from app.domain.entry_storage import _hash
from app.domain.entry_package_policy import PackagePolicy, policy_from_document as package_from_document
from app.domain.entry_process_policy import ProcessPolicy,policy_from_document
from app.domain.knowledge_publication_rules import PublicationPolicy
from app.domain.knowledge_publication import _policy as publication_document


@dataclass(frozen=True,init=False)
class SopReviewPolicy:
    encoded: str

    def __init__(self,value):
        shape(value,('format','reference','proof','operators','valid_from','review_due_on','rule_id',
            'definition_hash','source_hash','bundle_hash','projection_hash','catalog_hash',
            'publication_policy_hash','package_policy_hash','process_policy_hash','process_catalog_hash','source_mode'))
        definition=rules.definition(value['rule_id'])
        if (value['format']!=rules.FORMAT or value['source_hash']!=rules.SOURCE_HASH or
                value['definition_hash']!=_hash(definition) or
                value['source_mode']!='pinned_clause_internal_review_only'):
            rules.fail('operator_sop_policy_definition_invalid')
        for key,item in value.items():
            if key.endswith('_hash') or key=='proof':text(item,r'[a-f0-9]{64}')
        text(value['reference'],r'[A-Z][A-Z0-9._/-]{0,79}')
        operators=value['operators']
        if (type(operators) is not list or not 1<=len(operators)<=20 or
                any(type(v) is not str for v in operators) or len(set(operators))!=len(operators)):
            rules.fail('operator_sop_policy_operators_invalid')
        for operator in operators:
            text(operator,r'[a-z0-9_.-]{1,64}')
            if operator in ('system','bot'):rules.fail('operator_sop_policy_operators_invalid')
        if day(value['valid_from'])>day(value['review_due_on']):rules.fail('operator_sop_policy_dates_invalid')
        object.__setattr__(self,'encoded',json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False))

    @property
    def document(self):return json.loads(self.encoded)

    @property
    def digest(self):return _hash(self.document)


@dataclass(frozen=True)
class SopReviewAuthority:
    policy: SopReviewPolicy
    publication: PublicationPolicy
    process: ProcessPolicy
    package: PackagePolicy | None = None

    def __post_init__(self):self.validate()

    def validate(self):
        if not isinstance(self.policy,SopReviewPolicy) or not isinstance(self.publication,PublicationPolicy) or not isinstance(self.process,ProcessPolicy):
            rules.fail('operator_sop_authority_invalid')
        if self.package is not None and not isinstance(self.package,PackagePolicy):
            rules.fail('operator_sop_authority_invalid')
        value=self.policy.document
        if (value['package_policy_hash']!=_hash(self.package.document() if self.package else None) or
                value['publication_policy_hash']!=_hash(publication_document(self.publication)) or
                value['process_policy_hash']!=self.process.digest or value['process_catalog_hash']!=self.process.catalog_digest or
                not set(value['operators'])<=set(self.process.operators)):
            rules.fail('operator_sop_authority_changed')
        return self

    @property
    def document(self):
        self.validate()
        return dict(policy=self.policy.document,publication=publication_document(self.publication),process=self.process.document(),package=self.package.document() if self.package else None)


def from_document(value):
    shape(value,('policy','publication','process','package'))
    pp=value['publication'];shape(pp,('reference','fingerprint','publishers'))
    if type(pp['publishers']) is not list:rules.fail('operator_sop_authority_invalid')
    return SopReviewAuthority(SopReviewPolicy(value['policy']),
        PublicationPolicy(pp['reference'],pp['fingerprint'],tuple(pp['publishers'])),policy_from_document(value['process']),package_from_document(value['package']) if value['package'] else None)


def configured(settings,rule_id):
    values=getattr(settings,'kg_operator_sop_authorities',[])
    if type(values) is not list or len(values)>64:rules.fail('operator_sop_configuration_invalid')
    matches=[]
    for value in values:
        authority=from_document(value)
        if authority.policy.document['rule_id']==rule_id:matches.append(authority)
    if len(matches)>1:rules.fail('operator_sop_authority_ambiguous')
    return matches[0] if matches else None
