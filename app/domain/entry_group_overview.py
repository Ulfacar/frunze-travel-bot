"""Read-only whole-case progress of registered application chains (§14.1).

Labels describe the manual journal; they never certify a complete document set,
legal eligibility, delivery, travel readiness or commercial service completion.
"""
from collections import Counter, defaultdict

from sqlalchemy import or_, select

from app.domain import entry_applications as journal
from app.domain.entry_application_rules import MAX_APPLICANTS, MAX_ATTEMPTS, PROCEDURES, PROCESSES, RETRYABLE, ROLES, STATUSES
from app.domain.entry_storage import EntryStorageInvalid, _authorize, _id
from app.domain.models import EntryApplicant, EntryApplication, EntryApplicationEvent, EntryApplicationReference, Product, ServiceCase

MAX_OVERVIEW_APPLICATIONS = 2000
MAX_OVERVIEW_EVENTS = 20000
PEOPLE_PER_PAGE = 20
ATTENTION = frozenset(('revision_requested', 'refused', 'closed'))
FILTERS = {'all': 'Все заявители', 'attention': 'Есть доработка, отказ или закрытие',
           'without_applications': 'Нет заявок', 'draft': 'Есть черновики',
           'submitted': 'Есть заявки на рассмотрении', 'approved': 'Есть одобренные заявки'}
STATES = {'empty': 'Заявители ещё не добавлены', 'incomplete': 'Есть заявители без заявок',
          'attention': 'Есть заявки, требующие внимания', 'draft': 'Есть неподанные заявки',
          'submitted': 'Ожидаются решения', 'approved': 'Одобрения записаны по всем текущим заявкам'}


def _invalid():
    raise EntryStorageInvalid('application_integrity_failed')


async def _snapshot(session, case_id):
    # Creation uses an exclusive case lock. Lock all application parents in ID
    # order before reading events so writes cannot mix generations in PG READ
    # COMMITTED. SQLite's existing _run starts a physical read transaction.
    case = await session.scalar(select(ServiceCase).join(Product, Product.id == ServiceCase.product_id)
        .where(ServiceCase.id == case_id, Product.direction == 'visa').with_for_update(read=True, of=ServiceCase))
    if case is None:
        raise EntryStorageInvalid('application_case_unavailable')
    people = (await session.scalars(select(EntryApplicant).where(EntryApplicant.case_id == case_id)
        .order_by(EntryApplicant.ordinal).limit(MAX_APPLICANTS + 1))).all()
    applications = (await session.scalars(select(EntryApplication).where(EntryApplication.case_id == case_id)
        .order_by(EntryApplication.id).limit(MAX_OVERVIEW_APPLICATIONS + 1)
        .with_for_update(read=True, of=EntryApplication))).all()
    if len(people) > MAX_APPLICANTS or len(applications) > MAX_OVERVIEW_APPLICATIONS:
        raise EntryStorageInvalid('group_overview_too_large')
    # A SQL subquery avoids the SQLite bind-parameter limit on large groups.
    ids = select(EntryApplication.id).where(EntryApplication.case_id == case_id)
    events = (await session.scalars(select(EntryApplicationEvent).where(or_(
        EntryApplicationEvent.case_id == case_id, EntryApplicationEvent.application_id.in_(ids)))
        .order_by(EntryApplicationEvent.application_id, EntryApplicationEvent.revision)
        .limit(MAX_OVERVIEW_EVENTS + 1))).all()
    if len(events) > MAX_OVERVIEW_EVENTS:
        raise EntryStorageInvalid('group_overview_too_large')
    references = (await session.scalars(select(EntryApplicationReference).where(or_(
        EntryApplicationReference.case_id == case_id, EntryApplicationReference.application_id.in_(ids)))
        .limit(MAX_OVERVIEW_APPLICATIONS + 1))).all()
    foreign_child = await session.scalar(select(EntryApplication.id).where(
        EntryApplication.case_id != case_id, EntryApplication.previous_id.in_(ids)).limit(1))
    if foreign_child is not None:
        _invalid()

    person_ids, ordinals = set(), set()
    for person in people:
        journal._checked(person, journal._applicant_command, journal._applicant_payload)
        if person.role not in ROLES or not 1 <= person.ordinal <= MAX_APPLICANTS or person.ordinal in ordinals:
            _invalid()
        person_ids.add(person.id); ordinals.add(person.ordinal)
    by_id = {row.id: row for row in applications}
    grouped, refs = defaultdict(list), {}
    for row in events:
        if row.application_id not in by_id or row.case_id != case_id:
            _invalid()
        grouped[row.application_id].append(row)
    for row in references:
        if row.application_id not in by_id or row.case_id != case_id or row.application_id in refs:
            _invalid()
        refs[row.application_id] = row
    for row in applications:
        journal._checked(row, journal._application_command, journal._application_payload)
        if row.procedure not in PROCEDURES or row.applicant_id not in person_ids or not 1 <= row.attempt <= MAX_ATTEMPTS:
            _invalid()
        journal._validate_events(row, grouped[row.id], refs.get(row.id))

    successors = {}
    for row in applications:
        if (row.previous_id is None) != (row.attempt == 1):
            _invalid()
        if row.previous_id is not None:
            old = by_id.get(row.previous_id)
            if (old is None or old.id >= row.id or old.applicant_id != row.applicant_id or
                old.procedure != row.procedure or old.attempt + 1 != row.attempt or
                grouped[old.id][-1].status not in RETRYABLE or old.id in successors):
                _invalid()
            successors[old.id] = row.id
    return [journal._applicant_view(row) for row in people], [
        {**journal._application_view(row), 'current': journal._event_view(grouped[row.id][-1]),
         'successor_id': successors.get(row.id)} for row in applications]


def _counts(rows):
    counts = Counter(row['current']['status'] for row in rows)
    return {status: counts[status] for status in STATUSES}


def _aggregate(people, applications):
    current = [row for row in applications if row['successor_id'] is None]
    by_person, historic = defaultdict(list), Counter()
    for row in applications:
        if row['successor_id'] is None:
            by_person[row['applicant_id']].append(row)
        else:
            historic[row['applicant_id']] += 1
    groups = [{**person, 'applications': by_person[person['id']],
               'historical_count': historic[person['id']], 'counts': _counts(by_person[person['id']])}
              for person in people]
    missing = sum(not person['applications'] for person in groups)
    counts = _counts(current)
    # Exceptions are separate attention signals, not a claimed order of legal
    # stages. Show every counter even when the heading describes only one gap.
    state = ('empty' if not people else 'incomplete' if missing else
             'attention' if any(counts[status] for status in ATTENTION) else
             'draft' if counts['draft'] else 'submitted' if counts['submitted'] else 'approved')
    return {'people': groups, 'state': state, 'counts': counts,
            'total_people': len(people), 'without_applications': missing,
            'total_applications': len(applications), 'current_applications': len(current),
            'historical_applications': len(applications) - len(current),
            'processes': {process: _counts([row for row in current if row['process'] == process]) for process in PROCESSES}}


async def read_group_overview(engine, *, actor, case_id, page=1, selection='all'):
    _authorize(actor); _id(case_id)
    if type(page) is not int or not 1 <= page <= 100000 or not isinstance(selection, str) or selection not in FILTERS:
        raise EntryStorageInvalid('invalid_group_filter')
    async def read(session):
        people, applications = await _snapshot(session, case_id)
        result = _aggregate(people, applications)
        groups = result['people']
        if selection == 'without_applications':
            groups = [person for person in groups if not person['applications']]
        elif selection == 'attention':
            groups = [person for person in groups if any(person['counts'][status] for status in ATTENTION)]
        elif selection != 'all':
            groups = [person for person in groups if person['counts'][selection]]
        total = len(groups)
        # Clamp an old page after data/filter changes; do not display a blank
        # slice while claiming that people match the filter.
        actual_page = min(page, max(1, (total + PEOPLE_PER_PAGE - 1) // PEOPLE_PER_PAGE))
        start = (actual_page - 1) * PEOPLE_PER_PAGE
        result.update(people=groups[start:start + PEOPLE_PER_PAGE], matching_people=total,
                      page=actual_page, selection=selection, has_next=total > start + PEOPLE_PER_PAGE,
                      first=start + 1 if total else 0, last=min(start + PEOPLE_PER_PAGE, total),
                      read_at=journal._utc(journal._now()))
        return result
    return await journal._run(engine, read)
