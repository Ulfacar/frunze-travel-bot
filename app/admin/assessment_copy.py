"""Human-readable assessment reasons; internal identifiers stay out of the flow."""
from app.admin.qualification_copy import REASONS as ROUTE_REASONS, reasons as route_reasons

REASONS = dict(ROUTE_REASONS)


def group(codes, ru, en):
    for code in codes.split():
        REASONS[code] = (ru, en)


group('assessment_authority_missing assessment_authority_source_changed assessment_authority_outside_validity',
      'Для этой версии базы ещё нет действующего утверждения полной проверки. Передайте вопрос специалисту.',
      'This knowledge version has no current approval for the complete assessment. Refer it to a specialist.')
group('assessment_regime_set_incomplete assessment_source_coverage_incomplete assessment_source_interpretation_changed assessment_guard_country_unknown assessment_default_partition_required assessment_manual_applicability_changed assessment_manual_country_scope_changed assessment_executable_scope_unsupported assessment_counting_source_conflict assessment_profile_mapping_changed',
      'Утверждённая трактовка не покрывает все условия источника или противоречит им. Нужна сверка правил.',
      'The approved interpretation does not cover all source conditions or conflicts with them. The rules need review.')
group('assessment_source_unavailable', 'Нужные правила не доступны в действующей утверждённой публикации.',
      'Required rules are unavailable in the current approved publication.')
group('assessment_authority_does_not_cover_trip interview_authority_does_not_cover_trip',
      'Срок утверждения проверки не покрывает всю поездку.', 'The assessment approval does not cover the whole trip.')
group('business_mapping_requires_specialist',
      'Деловую поездку должен проверить специалист: подбор деловой визы B здесь ещё не утверждён.',
      'A specialist must review this business trip: business visa B routing is not approved here yet.')
group('individual_assessment_scope_requires_specialist interview_scope_requires_specialist interview_branch_requires_specialist',
      'Обстоятельства выходят за рамки проверки обычной индивидуальной туристической поездки. Нужен специалист.',
      'These circumstances are outside the supported ordinary individual tourism assessment. Specialist review is required.')
group('additional_profile_evidence_requires_reconciliation profile_condition_facts_conflict',
      'Дополнительные сведения в анкете нужно сверить с интервью и личной историей.',
      'Additional profile facts need reconciliation with the interview and personal history.')
group('personal_history_missing', 'Заполните и подтвердите личную историю поездок этого заявителя, включая отсутствие поездок.',
      'Record and confirm this applicant’s personal travel history, including an explicit absence of visits.')
group('personal_history_withdrawn', 'Личная история отозвана. Сначала внесите актуальные подтверждённые сведения.',
      'The personal history was withdrawn. Record current confirmed facts first.')
group('personal_history_review_required personal_history_basis_or_passport_requires_review',
      'История требует проверки: полнота, актуальность, основание пребывания и тот же паспорт должны быть подтверждены.',
      'Verify the history: completeness, currentness, basis of stay and use of the same passport must be confirmed.')
group('personal_history_open_visit personal_history_plan_overlap personal_history_overlapping_visits',
      'В истории есть незакрытая или пересекающаяся поездка. Уточните даты перед расчётом нового въезда.',
      'The history contains an open or overlapping visit. Clarify the dates before assessing a new entry.')
group('interview_missing interview_active interview_unstarted',
      'Завершите интервью именно этого заявителя и передайте заполненную карточку ответственному менеджеру.',
      'Complete this applicant’s interview and hand the completed card to the responsible manager.')
group('interview_pending', 'Заполненная карточка ожидает принятия ответственным менеджером.',
      'The completed interview card is awaiting acknowledgment by its responsible manager.')
group('interview_paused', 'Интервью приостановлено. Продолжите его перед полной проверкой.',
      'The interview is paused. Resume it before the complete assessment.')
group('interview_consent_required', 'Согласие на обработку данных отсутствует или отозвано. Проверка не завершена.',
      'Data processing consent is missing or withdrawn. The assessment is incomplete.')
group('interview_stop_requires_specialist interview_handoff_requires_specialist',
      'В интервью есть причина для передачи специалисту. Откройте карточку передачи.',
      'The interview requires specialist handoff. Open its handoff card.')
group('interview_changed_after_ack interview_answers_incomplete_or_stale interview_profile_changed interview_profile_conflict',
      'Ответы интервью изменились, устарели или расходятся с последней анкетой. Нужна повторная сверка специалистом.',
      'Interview answers changed, became stale or disagree with the latest profile. A specialist must reconcile them.')
group('interview_bridge_changed interview_authority_changed interview_authority_unavailable interview_clock_uncertain',
      'Не удалось подтвердить актуальное разрешение и версию интервью. Передайте проверку ответственному менеджеру.',
      'The current interview authority or version could not be confirmed. Refer the assessment to its responsible manager.')
group('special_regime_facts_require_specialist applicable_manual_regime_requires_specialist',
      'Может применяться специальный режим. Его условия и документы должен проверить специалист.',
      'A special regime may apply. A specialist must verify its conditions and documents.')
group('interview_history_conflict interview_reported_history_conflict interview_reported_history_unresolved interview_history_incomplete',
      'Сведения о прошлых поездках или заявленном числе дней не совпадают с личной историей. Уточните их со специалистом.',
      'Previous visits or reported day counts do not match the personal history. Clarify them with a specialist.')
group('personal_stay_arithmetic_unsupported personal_stay_arithmetic_unresolved',
      'Для этих дат или обстоятельств расчёт не завершён. Нужна проверка специалиста.',
      'The calculation is incomplete for these dates or circumstances. Specialist review is required.')
group('planned_stay_exceeds_allowance',
      'Планируемая поездка превышает безвизовый лимит. Специалист должен проверить визу или другое основание пребывания.',
      'The planned trip exceeds the visa-free allowance. A specialist must review a visa or another basis of stay.')
group('stay_margin_requires_specialist',
      'В ходе поездки остаток безвизового лимита составит три дня или меньше. Нужна проверка менеджером по документам.',
      'The remaining visa-free allowance reaches three days or less during the trip. A manager must check the evidence.')
group('registration_default_coverage_unknown registration_country_coverage_unknown registration_exemption_unavailable registration_source_conflict',
      'Правило освобождения от регистрации отсутствует, недоступно или противоречиво. Срок регистрации не заменяет освобождение.',
      'The registration exemption is missing, unavailable or conflicting. A registration term cannot replace an exemption.')
group('registration_trip_exceeds_exemption registration_submission_requires_review',
      'Для поездки требуется проверка обязанности зарегистрироваться. Фактический срок подачи пока не рассчитан.',
      'The trip requires review of the registration obligation. An actual filing deadline has not been calculated.')


def reasons(report):
    index = int(report['language'] == 'en')
    labels = [REASONS.get(code, ('Нужна проверка специалиста.', 'Specialist review is required.'))[index]
              for code in report['reasons']]
    labels += route_reasons({**report, 'reasons': []})
    return list(dict.fromkeys(labels))
