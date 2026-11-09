# Контракты API и фоновой обработки

Это спецификация интерфейсов, не реализация и не готовый OpenAPI-файл. Во время разработки FastAPI должен публиковать OpenAPI с эквивалентными типами и ограничениями.

## Общие правила

- Базовый путь `/api/v1`; JSON для метаданных, бинарное тело для медиа.
- UI использует сессионную cookie; расширение — отзываемый токен `capture:write`. Токен записи не позволяет получать анализ, профиль или диалог.
- Все записи принадлежат единственному аккаунту; ссылки на UUID сами по себе не дают доступа.
- `Idempotency-Key` обязателен для создания сессий, импортов, заданий и сообщений. Повтор с тем же телом возвращает прежний результат; с другим — HTTP 409.
- Изменяемые ресурсы возвращают `revision`; PATCH требует ожидаемую ревизию. При конфликте — HTTP 409 без перезаписи пользовательских правок.
- Длительная операция возвращает HTTP 202: `job_id`, `status_url`, `events_url`. Синхронное создание — 201, чтение/исправление — 200, удаление без тела — 204.
- Ошибка: `code`, `message`, `retryable`, `details`, `request_id`. В сообщении нет секретов, полного prompt или чужих данных.
- Основные ошибки: 400 malformed_request, 401 unauthenticated, 403 forbidden, 404 not_found, 409 revision_conflict/state_conflict, 413 media_too_large, 422 invalid_pgn/unsupported_variant/invalid_position, 429 rate_limited, 503 dependency_unavailable, 507 storage_full.

## Доступ владельца и расширения

POST `/auth/login` принимает пароль единственного аккаунта и устанавливает сессионную cookie; POST `/auth/logout` отзывает сессию. Пароль задаётся при установке, хранится как Argon2id-хеш; публичной регистрации нет. Вход ограничивается по частоте.

POST `/capture-tokens` доступен только владельцу в UI: создаёт токен с меткой устройства и возвращает секрет один раз для переноса в настройки расширения. DELETE `/capture-tokens/{id}` отзывает токен. На сервере хранится хеш, на клиенте — локальное хранилище расширения без синхронизации браузерного аккаунта. В запросах разрешены только HTTPS и настроенный адрес сервера; CORS ограничен UI и конкретным extension origin.

Capture-токен может создавать и дополнять собственные recording-сессии, читать их manifest и состояние загрузки. Импорт/анализ партий, доступ к сохранённым медиа и все операции корпуса требуют сессии владельца. Финализация записи сохраняет файлы; дальнейшую обработку запускает UI после проверки завершения партии.

## Запись и импорт

| Метод и маршрут | Вход | Выход / правило |
|---|---|---|
| POST `/recordings` | client_session_id, source, external_game_id?, capture_mode | session_id, revision; client_session_id уникален для владельца |
| PUT `/recordings/{id}/chunks/{segment}/{sequence}` | Бинарный блок, Content-Type, SHA-256, media_start/end_ms | asset_id, digest; повтор того же содержимого безопасен, конфликт digest → 409 |
| POST `/recordings/{id}/observations` | Пакет событий с уникальными sequence и временными опорами | accepted_sequences, rejected_items; дубли не размножаются |
| GET `/recordings/{id}/manifest` | — | Принятые блоки и события, gaps, состояние загрузки |
| POST `/recordings/{id}/finalize` | expected_revision, manifest, ended_at | Проверка полноты и digest; job_id или список пропусков |
| POST `/games/import` | Один из pgn_text / lichess_game_id; recording_id?, player_color?, completion_declaration? | job_id; несколько партий в одном PGN в v1 отклоняются |
| GET `/games/{id}` | — | Ревизия, метаданные, состояние завершения, ходы и позиции |
| POST `/games/{id}/transcriptions` | recording_id, config_id | job_id; только завершённая партия |
| PATCH `/utterances/{id}` | expected_revision, edited_text | Новая transcript_revision; оригинал сохранён |
| PATCH `/games/{id}/alignment` | expected_revision, список связей utterance → position/relation | Новая alignment_revision и зависимые stale IDs |
| GET `/games/{id}/timeline` | revision? | Позиции, реплики, медиа-интервалы, проблемы и freshness |

Для внешнего аудио клиент создаёт сессию с `capture_mode=imported_audio`, загружает файл как один asset через тот же chunk-контракт и финализирует манифест. Первая версия ограничивает отдельный upload 100 MiB; большие записи передаются блоками. Прямой импорт видео — resumable загрузка блоками, с общим лимитом 2 GiB на asset. Эти лимиты конфигурируются, но обход их бесконтрольным URL fetch запрещён.

URL Lichess разбирается в game ID; сервер не скачивает произвольные URL от имени клиента. Источники видео обслуживает отдельный адаптер с разрешёнными доменами и запретом доступа к внутренним адресам.

## Анализ и разговор

| Метод и маршрут | Вход | Выход / правило |
|---|---|---|
| POST `/games/{id}/analyses` | game_revision, alignment_revision, config_id | job_id; одна задача на одинаковую конфигурацию и входы |
| GET `/analyses/{id}` | — | Проверенные факты, утверждения, важные моменты, версии и freshness |
| POST `/conversations` | analysis_run_id, profile_version_id, position_ref | conversation_id; профиль опубликован, входы current |
| POST `/conversations/{id}/messages` | text, position_ref, client_message_id | job_id; у разговора только одна активная генерация |
| POST `/conversations/{id}/voice-inputs` | audio_asset_id | job_id распознавания; текст возвращается на подтверждение, не отправляется тренеру автоматически |
| GET `/conversations/{id}/messages` | cursor? | История с позициями, проверенными вариантами и freshness |
| POST `/messages/{id}/feedback` | usefulness 1..5, error_tags, comment? | Сохранённая оценка; не изменяет опубликованный ответ |

`position_ref` — либо ID позиции основной партии, либо базовая позиция и список UCI-ходов варианта. Сервер восстанавливает и проверяет позицию. Переданный клиентом FEN не принимается как единственное основание для ответа.

Ответ тренера содержит:

| Поле | Назначение |
|---|---|
| position_ref | Точная позиция обсуждения |
| text | Проверенный текст для пользователя |
| claim_assessments | Ссылки на мысли и их оценки; неизвестность допустима |
| lines | Легальные варианты UCI с опорной позицией и подписями |
| board_annotations | Подсветки полей/стрелки, проверенные относительно позиции |
| follow_up_question? | Не более одного основного вопроса за ответ |
| grounding_status | author_supported / general_chess / insufficient_context |
| evidence_refs | Внутренние основания; не выводятся в обычном режиме |
| versions | Профиль, модель, prompt, поиск и движок |

Обычный UI получает необходимые для показа поля; внутренние prompts и сырые provider responses доступны только диагностическому маршруту владельца.

## Корпус и профили

| Метод и маршрут | Вход | Выход / правило |
|---|---|---|
| POST `/sources` | author_id, youtube_url или asset_id, metadata | source_id, состояние доступности |
| POST `/sources/{id}/extractions` | extraction_config_id, split_group | job_id; повтор не перезаписывает ручную проверку |
| GET `/sources/{id}/episodes` | state?, cursor? | Эпизоды и проблемные привязки |
| PATCH `/episodes/{id}` | expected_revision, исправляемые поля | Новая версия draft/needs_review |
| POST `/episodes/{id}/reviews` | revision, verdict verified/rejected, notes | Решение проверки; verified требует непротиворечивую позицию и источник |
| POST `/authors/{id}/profiles` | train_episode_versions, config_id, split_manifest_id | job_id построения draft-профиля |
| PATCH `/profiles/{id}` | expected_revision, principles, coverage_notes | Исправленный draft; ссылки на основания обязательны |
| POST `/profiles/{id}/publish` | expected_revision, review_note | Опубликованная версия; исключает holdout-эпизоды |
| GET `/authors/{id}/profiles` | — | Версии, состояния, покрытие |
| POST `/evaluations` | dataset_version, candidate_configs, protocol_version | job_id сравнения |

Операции удаления партий, записей и источников — DELETE соответствующего ресурса с expected_revision и явным объёмом удаления. Они создают фоновое задание удаления файлов и зависимых данных; до завершения объекты исключаются из обработки и выдачи.

## Задания и события

GET `/jobs/{id}` возвращает status, phase, progress, attempt, input_versions, result_ref и error. POST `/jobs/{id}/cancel` запрашивает отмену. Уже завершённый внешний вызов может быть оплачен; его результат не публикуется после отмены.

GET `/jobs/{id}/events` — SSE с последовательными event ID и поддержкой Last-Event-ID. Типы событий: queued, started, phase_changed, progress, retry_scheduled, completed, failed, cancelled. Событие completed ссылается на сохранённый результат. Потеря SSE не означает потерю задания: GET остаётся источником текущего состояния.

Запуск worker передаёт `job_id`, а не медиа или prompts через Redis. Worker читает зафиксированные входные версии из БД. Создание job и outbox-записи атомарно. Dispatcher публикует очередь с повторной доставкой; worker использует dedup_key и атомарную смену состояния.

## Контракты провайдеров

| Адаптер | Вход | Обязательный результат |
|---|---|---|
| ASR | MediaAsset, язык, словарь терминов | Сегменты со временем, сырой текст, model ID, usage; отсутствие word timestamps явно отмечено |
| VideoUnderstanding | Источник/фрагмент, запрос извлечения | Кандидаты эпизодов, интервалы и наблюдения доски; не verified автоматически |
| TextReasoning | Тип задачи, структурированные факты, контекст | Схемно валидный результат, usage, model ID; дополнительный текст вне схемы не публикуется |
| Embeddings | Тексты, model ID | Векторы фиксированной размерности, версия и usage |
| ChessEngine | Позиция с историей, кандидаты, бюджет | Легальные PV, score perspective, depth/nodes/time, build/NNUE ID |

Модель, prompt, параметры генерации и цена фиксируются конфигурацией эксперимента. Отсутствующие поля не восстанавливаются молча догадкой. Совместимость проверяется контрактными тестами на каждом изменении адаптера.
