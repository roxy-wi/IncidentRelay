---
title: Настройка голосового провайдера
description: Настройка голосового провайдера IncidentRelay
---

# Настройка голосового провайдера

## Основная конфигурация IncidentRelay

IncidentRelay читает настройки голосового провайдера из основного файла конфигурации.

Пример:

```ini
[voice]
provider = stub
providers_dir = /usr/local/lib/incidentrelay/voice_providers
callback_secret = change-me
text_template = IncidentRelay alert {alert_id}. {title}. Severity {severity}. {message}. Press 1 to acknowledge. Press 2 to resolve.
dtmf_actions = {"1": "acknowledge", "2": "resolve"}

[voice_provider]
api_url = https://voice.example.com/api
api_token = ${VOICE_API_TOKEN}
timeout = 10
```

## Настройки

### provider

Имя провайдера по умолчанию.

Канал уведомлений может переопределить это значение в своей собственной конфигурации:

```json
{
  "provider": "mango"
}
```

### providers_dir

Каталог, в котором хранятся пользовательские модули провайдеров.

Рекомендуемое значение:

```text
/usr/local/lib/incidentrelay/voice_providers
```

### callback_secret

Глобальный резервный секрет для голосовых колбэков.

URL колбэков провайдера используют такой формат:

```text
/api/integrations/voice/callback/{channel_id}/{secret}
```

Если конфигурация канала содержит `callback_secret`, IncidentRelay использует секрет канала вместо глобального.

## Имена файлов провайдеров

Имена файлов провайдеров должны содержать только буквы, цифры и подчёркивание.

Допустимые примеры:

```text
mango.py
zadarma.py
internal_pbx.py
voice_gateway_1.py
```

Недопустимые примеры:

```text
mango-provider.py
my.provider.py
provider backup.py
```

Имя провайдера, используемое в конфигурации канала, — это имя файла без `.py`.

Пример файла:

```text
/usr/local/lib/incidentrelay/voice_providers/mango.py
```

Имя провайдера:

```json
"provider": "mango"
```

## Конфигурация канала

Пример конфигурации голосового канала:

```json
{
  "provider": "example_http",
  "call_on_severities": ["critical", "high"],
  "test_phone": "+77001234567",
  "callback_secret": "change-me-channel-secret",
  "text_template": "IncidentRelay alert {alert_id}. {title}. Severity {severity}. {message}. Press 1 to acknowledge. Press 2 to resolve.",
  "dtmf_actions": {
    "1": "acknowledge",
    "2": "resolve"
  },
  "provider_config": {
    "api_url": "https://voice.example.com/api",
    "api_token": "${VOICE_API_TOKEN}",
    "from": "+77000000000",
    "timeout": 10
  }
}
```

## Поля конфигурации канала

### provider

Имя модуля провайдера.

```json
"provider": "mango"
```

### call_on_severities

Список уровней важности, которые должны инициировать телефонный вызов.

```json
"call_on_severities": ["critical", "high"]
```

Если этот список пуст, IncidentRelay не будет звонить никому по реальным алертам.

### phone

Необязательный резервный номер телефона.

Для реальных алертов IncidentRelay обычно использует номер телефона назначенного пользователя.

```json
"phone": "+77001234567"
```

### test_phone

Номер телефона, используемый для тестовых вызовов.

```json
"test_phone": "+77001234567"
```

### callback_secret

Необязательный секрет колбэка на уровне канала.

Если он опущен, IncidentRelay использует глобальную конфигурацию:

```ini
[voice]
callback_secret = change-me
```

### text_template

Шаблон произносимого сообщения.

Поддерживаемые плейсхолдеры:

```text
{alert_id}
{event_type}
{title}
{message}
{severity}
{status}
{team}
{assignee}
{source}
```

Пример:

```json
"text_template": "Alert {alert_id}. {title}. Severity {severity}. Press 1 to acknowledge. Press 2 to resolve."
```

### dtmf_actions

Сопоставляет цифры телефонной клавиатуры с действиями IncidentRelay.

```json
"dtmf_actions": {
  "1": "acknowledge",
  "2": "resolve"
}
```

Поддерживаемые действия:

```text
acknowledge
resolve
```

### provider_config

Настройки, специфичные для провайдера.

IncidentRelay передаёт этот объект в конструктор провайдера.

```json
"provider_config": {
  "api_url": "https://voice.example.com/api",
  "api_token": "${VOICE_API_TOKEN}",
  "from": "+77000000000",
  "timeout": 10
}
```

Секреты следует хранить в переменных окружения и ссылаться на них как `${ENV_NAME}`.

```json
"api_token": "${VOICE_API_TOKEN}"
```

## Проверка конфигурации

Провайдер может определить `validate_config()`.

Этот метод вызывается перед использованием провайдера.

```python
class Provider(BaseVoiceProvider):
    name = "mango"

    @classmethod
    def validate_config(cls, config):
        """Validate required provider settings."""

        required_fields = ["api_url", "api_token"]

        missing = [
            field
            for field in required_fields
            if not config.get(field)
        ]

        if missing:
            raise RuntimeError(
                f"mango provider config requires: {', '.join(missing)}"
            )
```

Используйте этот метод для ранней проверки обязательных полей.

Хорошие сообщения об ошибках валидации важны, потому что они отображаются в логах и помогают пользователям быстрее исправить конфигурацию канала.
