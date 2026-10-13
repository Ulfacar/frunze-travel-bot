"""Manual processing facts, not publication of the PDF's operational workflows."""
ROLES = {'unknown': 'Роль пока не установлена', 'primary': 'Основной заявитель',
         'spouse': 'Супруг / супруга', 'child': 'Ребёнок', 'parent': 'Родитель',
         'employee': 'Сотрудник компании', 'other': 'Другой участник'}
PROCESSES = {'visa': 'Визы', 'work': 'Работа', 'stay': 'Пребывание', 'regularization': 'Урегулирование'}
PROCEDURES = {'visa': ('visa', 'Виза'), 'unified_permit': ('work', 'Единое разрешение'),
              'resident_card': ('work', 'Резидент-карта'), 'registration': ('stay', 'Регистрация'),
              'violation_protocol': ('regularization', 'Протокол нарушения'),
              'exit_visa': ('regularization', 'Выездная виза L')}
STATUSES = {'draft': 'Черновик', 'submitted': 'Подано / на рассмотрении',
            'revision_requested': 'Возвращено на доработку', 'approved': 'Одобрено',
            'refused': 'Отказ', 'closed': 'Закрыто в CRM без завершения'}
SOURCES = {'crm': 'Решение оператора в CRM', 'portal': 'Статус или письмо портала e-Visa',
           'official_document': 'Официальный документ / подтверждение', 'client_request': 'Обращение клиента'}
TRANSITIONS = {'draft': ('submitted', 'closed'), 'submitted': ('revision_requested', 'approved', 'refused', 'closed'),
               'revision_requested': ('submitted', 'refused', 'closed'), 'approved': (), 'refused': (), 'closed': ()}
RETRYABLE = {'refused', 'closed'}
MAX_APPLICANTS = 1000
MAX_EVENTS = 500
MAX_ATTEMPTS = 100
PAGE_SIZE = 20
