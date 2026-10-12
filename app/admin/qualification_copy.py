"""Operator-facing explanations for a route candidate, in both interview languages."""
from app.admin.kg_entry_form import STOP_LABELS

REASONS = {}


def group(codes, ru, en):
    for code in codes.split():
        REASONS[code] = (ru, en)


group('individual_profile_missing extended_individual_profile_required',
      'Сначала заполните расширенную анкету этого заявителя.', 'Complete this applicant’s extended profile first.')
group('individual_profile_changed individual_profile_needs_current_confirmation individual_profile_source_changed',
      'Анкета или источник изменились. Откройте последнюю анкету и подтвердите актуальные ответы.',
      'The profile or source has changed. Open the latest profile and confirm the current answers.')
group('interview_reconciliation_required', 'По заявителю уже ведётся интервью. Специалисту нужно сверить его ответы и статус передачи.',
      'An interview exists for this applicant. A specialist must reconcile its answers and handoff status.')
group('individual_profile_answers_conflict',
      'В сохранённой анкете есть несогласованные ответы. Откройте анкету и уточните их перед подбором.',
      'The saved profile contains inconsistent answers. Open the profile and clarify them before routing.')
group('no_active_publication competing_regime_unavailable', 'Не все необходимые правила доступны в действующей утверждённой публикации.',
      'Not all necessary rules are available in the current approved publication.')
group('qualification_policy_missing qualification_policy_source_changed qualification_policy_outside_validity',
      'Правила подбора для этой версии базы ещё не утверждены или срок их проверки истёк.',
      'The routing rules for this knowledge version are not approved or their review period has expired.')
group('qualification_regime_set_incomplete qualification_predicate_country_unknown qualification_source_semantics_unsupported qualification_predicates_do_not_cover_source qualification_product_does_not_cover_source qualification_condition_unresolved_or_changed qualification_condition_outcome_unsupported qualification_predicate_route_conflict',
      'Условия источника не полностью отражены в утверждённых правилах подбора. Нужна сверка специалистом.',
      'The approved routing rules do not fully cover the source conditions. Specialist review is required.')
group('profile_stop_requires_specialist', 'В анкете есть причина для передачи специалисту.',
      'The profile contains a reason for specialist handoff.')
group('individual_profile_incomplete competing_regime_facts_unknown', 'Для выбора недостаточно подтверждённых ответов.',
      'More confirmed answers are needed before a route can be identified.')
group('individual_route_scope_requires_specialist purpose_route_not_approved', 'Для этого обращения нужен индивидуальный подбор специалистом.',
      'This request requires individual routing by a specialist.')
group('passport_expires_before_departure', 'Документ истекает раньше планируемого выезда. Проверьте даты и документ.',
      'The travel document expires before the planned departure. Check the dates and document.')
group('qualification_policy_does_not_cover_trip source_does_not_cover_trip', 'Сроки проверки правил не покрывают всю поездку.',
      'The rules’ validity and review dates do not cover the whole trip.')
group('competing_regimes_match', 'Подходят несколько режимов. Специалист должен разрешить неоднозначность.',
      'Several regimes match. A specialist must resolve the ambiguity.')
group('no_supported_regime_matches', 'Однозначно подходящий режим не найден в поддерживаемых правилах.',
      'No unambiguous matching regime was found in the supported rules.')
group('individual_allowance_and_registration_not_evaluated', 'Вариант найден; личный остаток дней и регистрацию ещё нужно проверить.',
      'A candidate was found; individual remaining days and registration still need checking.')

STOP_EN = dict(special_document_review='Special travel document', work_purpose_review='Work-related purpose',
    passport_expired='Expired travel document', passport_pages_review='No blank passport pages',
    reported_overstay='Reported overstay', reported_deportation_or_ban='Reported deportation or entry ban',
    reported_refusal='Reported Kyrgyzstan refusal', current_basis_missing='No current basis of stay',
    current_basis_until_passed='Current basis of stay has expired', registration_until_passed='Registration has expired',
    planned_entry_in_past='The planned entry date has passed', reported_fines='Reported fines in Kyrgyzstan',
    large_group_review='More than five applicants', special_process_requested='Permit, residence or regularization requested',
    reported_complaint='Client complaint', reported_refund_question='Refund question', reported_legal_question='Legal question',
    reported_conflicting_answers='Conflicting client answers')


def reasons(report):
    index = 1 if report['language']=='en' else 0
    labels = [REASONS.get(code, ('Нужна проверка специалиста.', 'Specialist review is required.'))[index]
              for code in report['reasons']]
    stops = STOP_EN if index else STOP_LABELS
    labels.extend(stops.get(code, 'Specialist review is required.' if index else 'Нужна проверка специалиста.')
                  for code in report['stop_reasons'])
    return list(dict.fromkeys(labels))
