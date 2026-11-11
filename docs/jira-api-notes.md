# Разведка Jira Cloud

Проверено 11 ноября 2026 на отдельном тестовом Jira Cloud. Проект SCRUM, team-managed (`style=next-gen`, `simplified=true`), доска 1. Подготовлены 12 задач с префиксом [RECON] и меткой recon-20261111. Их ключи — SCRUM-5…SCRUM-16. Обычные задачи, существовавшие до разведки, в публикуемый набор ответов не включены.

## Как повторить запросы

В Postman создать локальные переменные `api_url`, `email`, `api_token`. Для исследованного обычного API-токена api_url равен адресу своего сайта вида https://example.atlassian.net. В Authorization выбрать Basic Auth, Username={{email}}, Password={{api_token}}. В Headers добавить Accept: application/json. Для POST поиска использовать Body → raw → JSON и Content-Type: application/json.

Секреты остаются локальными. Адрес тестового сайта и данные авторизации находятся в игнорируемом .env. Для токена со scopes документация требует API URL https://api.atlassian.com/ex/jira/{cloudId}; этот вариант в данной разведке не проверялся. В будущем нельзя заменять ссылку сотрудника на сайт API-адресом.

Начать с GET {{api_url}}/rest/api/3/myself, затем GET {{api_url}}/rest/api/3/project/SCRUM. Оба запроса вернули 200. Далее повторять операции из `jira-recon-requests.json`: method, path и body, если он задан. Каждый пример указывает HTTP-код и имя сохранённого fixture. Это список запросов, а не файл импорта Postman.

Файлы fixtures/raw сохраняют настоящую структуру ответов. Email, имена, accountId, аватары и домен сайта заменены. Числовые ID тестовых ресурсов и ключи SCRUM сохранены для связности примеров. Курсоры заменены на fixture-page-token-NNN. При живом повторении брать новые nextPageToken из предыдущего ответа, не отправлять заменённые значения из fixtures.

## Подготовленные случаи

| Ключ | Проверяемый случай |
| --- | --- |
| SCRUM-5 | intern-visible, назначенный исполнитель, активный спринт, In Progress, исходящая Blocks |
| SCRUM-6 | assignee=null, разрешающая метка, активный спринт |
| SCRUM-7 | Без intern-visible, активный спринт |
| SCRUM-8 | Бэклог, Sprint=null |
| SCRUM-9 | Будущий спринт 3, даты спринта отсутствуют |
| SCRUM-10 | Активный спринт 2 и завершённый спринт 4 в истории |
| SCRUM-11 | Пять комментариев, включая один ограниченный ролью Administrator |
| SCRUM-12 | Входящая сторона Blocks, без intern-visible, статус Done |
| SCRUM-13 | description=null, пустые optional-поля |
| SCRUM-14 | Форматированное описание и поле «Для практиканта» |
| SCRUM-15 | Явно вымышленные персональные сведения для будущего теста политики |
| SCRUM-16 | Снятие исполнителя и intern-visible, изменение описания |

Существующий активный спринт 2 сохранился. Созданы тестовый будущий спринт 3 и тестовый спринт 4, который был запущен, завершён, после чего SCRUM-10 перенесена в спринт 2. В примере Sprint у этой задачи видны состояния active и closed.

## Запросы

| Назначение | Метод и путь | Результат |
| --- | --- | --- |
| Текущая учётная запись | GET /rest/api/3/myself | 200, accountId и собственная почта |
| Проект | GET /rest/api/3/project/SCRUM | 200, id=10000, key=SCRUM |
| Поля | GET /rest/api/3/field | 200, schema и ID полей |
| Доски | GET /rest/agile/1.0/board?projectKeyOrId=SCRUM&maxResults=2 | 200, доска 1 |
| Конфигурация | GET /rest/agile/1.0/board/1/configuration | 200, колонки, статусы, ranking |
| Спринты | GET /rest/agile/1.0/board/1/sprint?startAt=0&maxResults=2 | 200, две страницы |
| Статусы | GET /rest/api/3/project/SCRUM/statuses | 200, категории статусов |
| Приоритеты | GET /rest/api/3/priority/search?maxResults=50 | 200, справочник приоритетов |
| Задача | GET /rest/api/3/issue/{key}?expand=renderedFields | 200, fields и renderedFields |
| Комментарии | GET /rest/api/3/issue/SCRUM-11/comment?startAt=0&maxResults=2&expand=renderedBody | 200, три страницы |
| Поиск | POST /rest/api/3/search/jql | 200, семь страниц для 12 тестовых задач |
| Задачи доски | GET /rest/software/1.0/board/1/issue | 200, семь страниц тестовых задач |
| Задачи спринта | GET /rest/software/1.0/sprint/2/issue | 200, четыре страницы для семи тестовых задач |
| Бэклог | GET /rest/software/1.0/board/1/backlog | 200, две страницы для трёх тестовых задач |

В запросах списков Software API использовались `maxResults=2`, явный fields и `jql=labels = "recon-20261111" ORDER BY key ASC`. Это объявленная область тестового набора. Фильтр не зависит от intern-visible, поэтому задачи с отозванным разрешением тоже попадают в обход. Для будущего реального полного sync область нужно определить настройкой проекта и не сужать только до разрешённых задач.

## Поля и сопоставление с DTO

| Наше поле | Наблюдаемый источник Jira | Примечание |
| --- | --- | --- |
| jira_id | issue.id | Строка с ID |
| key | issue.key | Например SCRUM-5 |
| project_key | fields.project.key | project.id нужен отдельно для JiraProject |
| summary | fields.summary | Строка |
| issue_type | fields.issuetype.name | На тестовом сайте локализовано как «Задание» |
| status.jira_id | fields.status.id | Устойчивый ключ статуса |
| status.category | fields.status.statusCategory.key | new→todo, indeterminate→in_progress, done→done |
| updated_at | fields.updated | В ответах полный timestamp с timezone, например +0000 |
| assignee.account_id | fields.assignee.accountId | У неназначенной задачи assignee=null |
| assignee.email | fields.assignee.emailAddress | Собственная почта присутствовала, скрытая почта не проверена |
| sprint | fields.customfield_10020 | null либо массив объектов спринтов, включая историю |
| rank | fields.customfield_10019 | LexoRank, например 0|i0000n: |
| priority | fields.priority | id, name, iconUrl; порядок будущего priority_order ещё согласовать |
| labels | fields.labels | Массив строк |
| description_html | renderedFields.description | HTML, требует очистки перед использованием |
| comments[].jira_id | comments[].id | Устойчивый ID комментария |
| comments[].created_at | comments[].created | Timestamp с timezone |
| comments[].author | comments[].author | accountId, displayName и дополнительные поля |
| comments[].body_html | comments[].renderedBody при expand=renderedBody | Тело body в API v3 — ADF |
| links | fields.issuelinks | outwardIssue/inwardIssue и type |
| custom_fields | Только согласованный белый список | Поле «Для практиканта» исследовано отдельно |

### Локализованные поля

Sprint найден как «Спринт» по schema.custom=com.pyxis.greenhopper.jira:gh-sprint, ID customfield_10020. Rank называется «Рейтинг», schema.custom=com.pyxis.greenhopper.jira:gh-lexo-rank, ID customfield_10019. Конфигурация доски подтверждает ranking.rankCustomFieldId=10019. Поиск поля только по английскому имени не подходит.

В конфигурации доски колонки To Do, In Progress, Done с ID статусов 10000, 10001, 10002. На уровне задачи имена статусов локализованы. Порядок колонок берётся из columnConfig.columns. Если позже несколько статусов попадут в одну колонку, правило их внутреннего порядка нужно определить отдельно.

### Поле «Для практиканта»

Создано поле customfield_10046 типа «Абзац», schema.type=string и custom=textarea. Оно относится к team-managed проекту. После создания поле было недоступно в editmeta задачи. Его нужно добавить в макет типа «Задание» и сохранить изменения. После этого запись через REST стала доступна.

В fields.customfield_10046 фактически приходит объект ADF, несмотря на schema.type=string. В renderedFields.customfield_10046 — HTML. Пустое значение в fields равно null, а в renderedFields в проверенных ответах — пустой строке.

### Описания, комментарии и связи

fields.description — ADF, renderedFields.description — HTML. Для пустого описания наблюдались null и пустая строка соответственно. В форматированном примере сохранились жирное выделение, список и ссылка на example.com. HTML остаётся входом для будущей очистки, наличие renderedFields не делает его автоматически разрешённым к выдаче.

Обычные комментарии не содержат visibility. Ограниченный комментарий содержит visibility.type=role и value/identifier=Administrator. Учётная запись администратора его читает. Проверка, что другой пользователь его не получает, не проводилась — второго тестового аккаунта нет. Нормализатор должен учитывать ограничение до формирования CommentDTO.

Blocks проверена с обеих сторон. В SCRUM-5 ссылка содержит outwardIssue.key=SCRUM-12, в SCRUM-12 — inwardIssue.key=SCRUM-5. У цели отсутствует intern-visible, что пригодится для будущего теста запрета выдачи ссылки на недоступную задачу.

## Пагинация

| Семейство | Параметры | Наблюдаемое окончание |
| --- | --- | --- |
| search/jql | nextPageToken, maxResults | isLast=true, nextPageToken отсутствует |
| Software board/sprint/backlog issue lists | nextPageToken, maxResults | isLast=true, nextPageToken отсутствует |
| Список спринтов | startAt, maxResults | isLast=true, также присутствует total |
| Комментарии | startAt, maxResults | startAt + число комментариев достигает total |

Поиск и список задач доски выдали по шесть страниц из двух задач и дополнительную седьмую пустую страницу с isLast=true. Нельзя заканчивать обход, просто получив ожидаемое количество задач или полную страницу. В списке спринта последняя страница содержала одну задачу, в бэклоге тоже одну. Комментарии пришли страницами 2+2+1, total=5. Спринты — 2+2, total=4.

Идентификаторы задач и комментариев проверены на отсутствие дублей между страницами. Отдельный поиск по несуществующей тестовой метке вернул issues=[] и isLast=true с HTTP 200. Это отличается от HTTP-ошибки или оборванного обхода.

## Различия между источниками одной задачи

При одинаковых 14 явно запрошенных полях и expand=renderedFields задача SCRUM-5 из issue, search/jql и sprint API имела одинаковый набор ключей fields и присутствующий renderedFields. Это проверено в issue_single_expanded.json, search_single_expanded.json, sprint_single_expanded.json. Значения нельзя считать гарантированно атомарным снимком для запросов, выполненных в разное время.

Без expand=renderedFields обычный issue-ответ не содержит этой секции. В большинстве сохранённых страничных запросов expand не запрашивался. Отсутствие незапрошенного поля нужно отличать от null.

## Изменения и отзыв разрешения

Сохранены issue_before_change.json и issue_after_change.json для SCRUM-16. Исполнитель изменён с тестового пользователя на null, intern-visible удалена, описание обновлено. fields.updated вырос. Поиск по ключу с reconcileIssues=[ID задачи] вернул задачу после изменения, с новыми значениями. Это подтверждает видимость отзыва в общем запросе при указанной сверке, но не измеряет задержку обычного поискового индекса.

В будущем необходимо обрабатывать уже сохранённую задачу, потерявшую разрешение. Пропуск её новой версии не закрывает старую запись. Полную очистку по отсутствию допускается выполнять только после успешного завершения всей объявленной области обхода.

## Ограничения и следующие решения

- В проекте доступен один назначаемый пользователь. Разделение между двумя accountId и скрытая почта на реальном ответе не проверены. Значения user1@example.test в fixtures заменяют собственную почту, а не доказывают, что Jira всегда возвращает email.
- Ограниченный комментарий получен администратором. Нужен второй пользователь для проверки фактического исключения по правам.
- Владелец owner_ref остаётся отдельным решением. Для варианта assignee можно использовать accountId, для label/custom_field нужна отдельная политика. Добавлять owner_ref в IssueDTO по результатам этой разведки не требуется.
- Sprint содержит историю. Предложение для нормализатора — активный, иначе ближайший будущий; выбор должен быть детерминированным и согласованным.
- Сохранён справочник приоритетов. Правило priority_order при записи ещё нужно согласовать.
- Исследование выполнено для одного team-managed проекта. Встраивание в среду Ламарта, лицензирование и способ её авторизации этим не подтверждены.

После ревью результатов можно приступать к DjangoStore и mock-sync на подготовленных DTO. Эти raw-ответы предназначены для будущих RestSource/нормализатора.

## Происхождение и контроль

Все примеры получены запросами к тестовому сайту 11 ноября 2026. Список 52 файлов и SHA256 текста UTF-8 с окончаниями строк LF находится в jira-recon-fixtures.json, повторяемые read-only запросы — в jira-recon-requests.json. Это позволяет проверить данные независимо от преобразования LF/CRLF в Windows. Файлы не являются выгрузкой рабочих данных Ламарта.

Официальные источники, сверенные при разведке — [Issue search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/), [Board API](https://developer.atlassian.com/cloud/jira/software/rest/api-group-board/), [Sprint API](https://developer.atlassian.com/cloud/jira/software/rest/api-group-sprint/), [Comments API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-comments/), [API tokens](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/).
