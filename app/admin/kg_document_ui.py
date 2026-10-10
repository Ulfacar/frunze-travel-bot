"""Shared document labels and response headers without router side effects."""
HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
STATES={'missing':'Нет документа','received':'Получен, ожидает проверки','checked':'Проверен',
        'correction':'Нужна доработка','withdrawn':'Отозван','recheck':'Нужна повторная проверка',
        'quarantined':'Файл в карантине — проверка недоступна'}
UNAVAILABLE={'application_case_unavailable','application_unavailable','applicant_unavailable'}
